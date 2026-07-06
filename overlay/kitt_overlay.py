#!/usr/bin/env python3
"""Nakładka KITT (Cocoa) dla simple-tts — parametryczne Core Animation.

Kropka to prawdziwy obiekt (CALayer): pozycja i skala są animowane, więc
przejścia są płynne, a kropka FIZYCZNIE przesuwa się w odpowiednie miejsce
(np. zbiega do środka przy mowie). Ogon = CAReplicatorLayer (opóźnione kopie).
Modulator „gadania" sterowany obwiednią odtwarzanego audio (simple-tts-speak.json),
więc pulsuje w rytm tego, co słychać. Wszystko na GPU -> ~0% CPU.

Stany (kitt_state): idle (wolny przejazd) / think (szybki) / speak (środek +
modulator) / None (wyłączone). Pływa nad pełnym ekranem (NSPanel, CanJoinAllSpaces
+ FullScreenAuxiliary). Pojedyncza instancja (flock).

Wymaga: pyobjc-framework-Cocoa, pyobjc-framework-Quartz, Pillow.
"""

import fcntl
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kitt_frame as KF  # noqa: E402
import kitt_state as KS  # noqa: E402
from AppKit import (  # noqa: E402
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSPanel,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakeRect, NSObject, NSTimer  # noqa: E402
from Quartz import (  # noqa: E402
    CABasicAnimation,
    CAKeyframeAnimation,
    CALayer,
    CAMediaTimingFunction,
    CAReplicatorLayer,
    CATransaction,
    CGColorSpaceCreateDeviceRGB,
    CGDataProviderCreateWithData,
    CGImageCreate,
    kCAAnimationLinear,
    kCAMediaTimingFunctionEaseInEaseOut,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
)

# --- konfiguracja ----------------------------------------------------------
W, H = 520, 40                 # punkty
SCALE = 2                      # render 2x (Retina)
Y_OFFSET = 6
MODE_CHECK_SEC = 0.25
DOT_D = 30                     # średnica świecącej kropki (pt)
MARGIN = DOT_D / 2.0 + 6.0     # by kropka nie wychodziła poza kadr
IDLE_HALF = 1.8                # sekundy na jeden przejazd L->R (idle)
THINK_SPEEDUP = 2.6            # „myśli" = szybciej (przez layer.speed)
CONVERGE_SEC = 0.35            # zbieganie do środka / powrót na tor
FADE_SEC = 0.35               # wejście/wyjście (opacity)
SPEAK_GAIN = 5.0               # maks. rozciągnięcie kropki w modulatorze
TAIL_COUNT = 8                 # kopie ogona
TAIL_DELAY = 0.045             # opóźnienie między kopiami (s)
TAIL_ALPHA = -0.12             # gaśnięcie ogona
SPEAK_STATE_PATH = os.path.expanduser("~/.claude/simple-tts-speak.json")
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")
LOCK_PATH = os.path.expanduser("~/.claude/simple-tts-overlay.lock")

_CS = CGColorSpaceCreateDeviceRGB()
_EASE = CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseInEaseOut)
_lock_handle = None
_MIDY = H / 2.0


def _log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _single_instance():
    global _lock_handle
    _lock_handle = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _dot_cgimage():
    px = int(DOT_D * SCALE)
    raw = KF.dot_sprite(px).tobytes()
    prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
    cg = CGImageCreate(px, px, 8, 32, px * 4, _CS,
                       kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                       prov, None, False, 0)
    return cg, raw            # raw musi żyć tak długo jak CGImage


# --- animacje (funkcje modułowe, operują na warstwie kropki) ---------------
def _pres_x(dot):
    pl = dot.presentationLayer()
    return (pl.position().x if pl is not None else dot.position().x)


def _sweep(dot, half):
    a = CABasicAnimation.animationWithKeyPath_("position.x")
    a.setFromValue_(MARGIN)
    a.setToValue_(W - MARGIN)
    a.setDuration_(half)
    a.setAutoreverses_(True)
    a.setRepeatCount_(1e9)
    a.setTimingFunction_(_EASE)
    a.setRemovedOnCompletion_(False)
    dot.setPosition_((MARGIN, _MIDY))
    dot.addAnimation_forKey_(a, "move")


def _to_sweep(dot):
    """Wejdź w przejazd: z bieżącej pozycji dojedź na tor, potem zapętl."""
    cur = _pres_x(dot)
    if abs(cur - MARGIN) < 1.5:
        _sweep(dot, IDLE_HALF)
        return
    dot.setPosition_((cur, _MIDY))                 # bez skoku po usunięciu anim
    intro = CABasicAnimation.animationWithKeyPath_("position.x")
    intro.setFromValue_(cur)
    intro.setToValue_(MARGIN)
    intro.setDuration_(CONVERGE_SEC)
    intro.setTimingFunction_(_EASE)
    intro.setRemovedOnCompletion_(False)
    dot.setPosition_((MARGIN, _MIDY))
    CATransaction.begin()
    CATransaction.setCompletionBlock_(lambda: _sweep(dot, IDLE_HALF))
    dot.addAnimation_forKey_(intro, "move")
    CATransaction.commit()


def _read_envelope():
    try:
        with open(SPEAK_STATE_PATH) as f:
            d = json.load(f)
        env, dt, start = d["env"], float(d["dt"]), float(d["start"])
        if not env:
            return None
        offset = time.time() - start
        if offset < 0 or offset >= len(env) * dt:   # brak/nieaktualne
            return None
        return env, dt, offset
    except (OSError, ValueError, KeyError):
        return None


def _modulate(dot):
    data = _read_envelope()
    if data:
        env, dt, offset = data
        a = CAKeyframeAnimation.animationWithKeyPath_("transform.scale.x")
        a.setValues_([1.0 + e * SPEAK_GAIN for e in env])
        a.setDuration_(len(env) * dt)
        a.setCalculationMode_(kCAAnimationLinear)
        a.setRemovedOnCompletion_(False)
        a.setTimeOffset_(offset)                   # sync do bieżącego miejsca audio
        dot.addAnimation_forKey_(a, "scale")
    else:                                          # brak obwiedni -> żywy puls
        a = CABasicAnimation.animationWithKeyPath_("transform.scale.x")
        a.setFromValue_(1.3)
        a.setToValue_(1.0 + SPEAK_GAIN * 0.6)
        a.setDuration_(0.26)
        a.setAutoreverses_(True)
        a.setRepeatCount_(1e9)
        a.setRemovedOnCompletion_(False)
        dot.addAnimation_forKey_(a, "scale")


def _to_speak(dot):
    """Zbiegnij do środka i zacznij modulować w rytm audio."""
    cur = _pres_x(dot)
    dot.setPosition_((cur, _MIDY))
    dot.removeAnimationForKey_("move")
    conv = CABasicAnimation.animationWithKeyPath_("position.x")
    conv.setFromValue_(cur)
    conv.setToValue_(W / 2.0)
    conv.setDuration_(CONVERGE_SEC)
    conv.setTimingFunction_(_EASE)
    conv.setRemovedOnCompletion_(False)
    dot.setPosition_((W / 2.0, _MIDY))
    dot.addAnimation_forKey_(conv, "move")
    _modulate(dot)


def _leave_speak(dot):
    dot.removeAnimationForKey_("scale")            # skala wraca do 1


def _fade(layer, to):
    pl = layer.presentationLayer()
    frm = pl.opacity() if pl is not None else layer.opacity()
    a = CABasicAnimation.animationWithKeyPath_("opacity")
    a.setFromValue_(frm)
    a.setToValue_(to)
    a.setDuration_(FADE_SEC)
    layer.setOpacity_(to)
    layer.addAnimation_forKey_(a, "fade")


def make_panel(cgimg):
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False)
    panel.setLevel_(NSScreenSaverWindowLevel)
    panel.setFloatingPanel_(True)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setIgnoresMouseEvents_(True)
    panel.setHasShadow_(False)

    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
    view.setWantsLayer_(True)
    rep = CAReplicatorLayer.layer()               # ogon: opóźnione kopie kropki
    rep.setFrame_(NSMakeRect(0, 0, W, H))
    rep.setInstanceCount_(TAIL_COUNT)
    rep.setInstanceDelay_(TAIL_DELAY)
    rep.setInstanceAlphaOffset_(TAIL_ALPHA)
    rep.setOpacity_(0.0)
    dot = CALayer.layer()
    dot.setBounds_(((0.0, 0.0), (DOT_D, DOT_D)))
    dot.setContentsGravity_("resizeAspect")
    dot.setContentsScale_(SCALE)
    dot.setContents_(cgimg)
    dot.setPosition_((MARGIN, _MIDY))
    rep.addSublayer_(dot)
    view.layer().addSublayer_(rep)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, dot, rep


def top_center(sf):
    x = sf.origin.x + (sf.size.width - W) / 2.0
    y = sf.origin.y + sf.size.height - H - Y_OFFSET
    return x, y


class Controller(NSObject):
    def check_(self, timer):
        try:
            screens = NSScreen.screens()
            for i, ent in enumerate(self.entries):
                if i < len(screens):
                    ent["panel"].setFrameOrigin_(top_center(screens[i].frame()))
            mode = KS.current_mode()
            if mode == self.curmode:
                return
            self.curmode = mode
            self.applyMode_(mode)
        except Exception:
            _log("check FAILED:\n" + traceback.format_exc())

    def applyMode_(self, mode):
        old = self.prevmode
        self.prevmode = mode
        for ent in self.entries:
            dot, rep = ent["dot"], ent["rep"]
            if mode is None:
                _fade(rep, 0.0)
                continue
            _fade(rep, 1.0)
            if old == "speak" and mode != "speak":
                _leave_speak(dot)
            if mode in ("idle", "think"):
                dot.setSpeed_(THINK_SPEEDUP if mode == "think" else 1.0)
                if old not in ("idle", "think"):
                    _to_sweep(dot)
            else:                                  # speak
                dot.setSpeed_(1.0)
                _to_speak(dot)


def main():
    if not _single_instance():
        _log("inna instancja nakładki już działa — wychodzę")
        return

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    cgimg, raw = _dot_cgimage()

    entries = []
    for s in NSScreen.screens():
        panel, dot, rep = make_panel(cgimg)
        panel.setFrameOrigin_(top_center(s.frame()))
        entries.append({"panel": panel, "dot": dot, "rep": rep})
    _log(f"start (CA): {len(entries)} ekran(ów)")

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl.curmode = "__none__"
    ctrl.prevmode = "__init__"
    ctrl._raw = raw                                # utrzymaj bajty CGImage
    ctrl.check_(None)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        MODE_CHECK_SEC, ctrl, b"check:", None, True)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
