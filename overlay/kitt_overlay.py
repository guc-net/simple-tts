#!/usr/bin/env python3
"""Nakładka KITT (Cocoa) dla simple-tts — pływa NAD pełnoekranowym terminalem.

Wydajność: klatki każdego trybu są renderowane RAZ (tym samym rendererem PIL —
wygląd 1:1) i przekazywane do Core Animation jako CAKeyframeAnimation na
`layer.contents`. Cyklowanie klatek robi window server na GPU, w osobnym wątku —
nasz proces nie robi nic per-klatkę (~0% CPU w stanie ustalonym). Jedyny timer
to lekki podgląd stanu co MODE_CHECK_SEC, który przy zmianie trybu podmienia
animację.

Trzy tryby wg stanu simple-tts (patrz kitt_state):
  idle  -> kropka + gasnący ogon jeździ prawo<->lewo
  think -> dwie kropki nerwowo gonią się (Claude pracuje)
  speak -> modulator głosu (simple-tts właśnie mówi)

Przezroczyste, klik-przechodzące NSPanel na każdym ekranie, na wysokim poziomie
z CanJoinAllSpaces + FullScreenAuxiliary. Wymaga: pyobjc-framework-Cocoa,
pyobjc-framework-Quartz, Pillow.
"""

import fcntl
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
    CGColorSpaceCreateDeviceRGB,
    CGDataProviderCreateWithData,
    CGImageCreate,
    kCAAnimationDiscrete,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
)

W, H = 520, 40             # rozmiar w punktach
SCALE = 2                  # render 2x (Retina)
Y_OFFSET = 6               # od górnej krawędzi ekranu
MODE_CHECK_SEC = 0.25      # jak często sprawdzać stan (jedyny timer)
BUILD_FPS = 16             # gęstość klatek w prekompute
THINK_SPEEDUP = 2.6        # „myśli" to ta sama kropka co idle, tylko szybciej
ALPHA_BOOST = 2.2          # krycie: jaśniej = bardziej kryjące
CROSSFADE_SEC = 0.35       # płynne przenikanie między animacjami stanów
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")
LOCK_PATH = os.path.expanduser("~/.claude/simple-tts-overlay.lock")

_CS = CGColorSpaceCreateDeviceRGB()
_lock_handle = None


def _single_instance():
    """True gdy udało się zająć blokadę — inaczej działa już inna nakładka."""
    global _lock_handle
    _lock_handle = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _mode_period(mode):
    if mode == "idle":
        return 2 * KF.SWEEP_SEC              # bezszwowa pętla (fala trójkątna)
    if mode == "think":
        return 2 * KF.SWEEP_SEC / THINK_SPEEDUP   # ta sama kropka, szybciej
    return 2.4                               # speak: pętla ~2.4 s


def _build_frames(mode):
    """Renderuj jeden okres trybu -> lista CGImage. Zwraca (frames, keep_bytes,
    period). keep_bytes trzeba utrzymać przy życiu (CGImage nie kopiuje danych)."""
    period = _mode_period(mode)
    pw, ph = W * SCALE, H * SCALE
    n = max(2, round(period * BUILD_FPS))
    frames, keep = [], []
    for k in range(n):
        t = k * period / n
        frame = KF.render(pw, ph, t, mode)
        alpha = frame.convert("L").point(lambda v: min(255, int(v * ALPHA_BOOST)))
        rgba = frame.convert("RGBA")
        rgba.putalpha(alpha)
        raw = rgba.tobytes()
        keep.append(raw)
        prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
        cg = CGImageCreate(pw, ph, 8, 32, pw * 4, _CS,
                           kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                           prov, None, False, 0)
        frames.append(cg)
    return frames, keep, period


def make_panel():
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
    # dwie nakładające się warstwy A/B — zmiana stanu przenika A<->B (crossfade)
    layers = []
    for _ in range(2):
        lyr = CALayer.layer()
        lyr.setFrame_(NSMakeRect(0, 0, W, H))
        lyr.setContentsGravity_("resize")
        lyr.setContentsScale_(SCALE)
        lyr.setOpacity_(0.0)
        view.layer().addSublayer_(lyr)
        layers.append(lyr)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, layers


def top_center(screen_frame):
    x = screen_frame.origin.x + (screen_frame.size.width - W) / 2.0
    y = screen_frame.origin.y + screen_frame.size.height - H - Y_OFFSET
    return x, y


def _fade(layer, to):
    """Płynnie zmień krycie warstwy do `to` (od bieżącego, widocznego stanu)."""
    pres = layer.presentationLayer()
    frm = pres.opacity() if pres is not None else layer.opacity()
    anim = CABasicAnimation.animationWithKeyPath_("opacity")
    anim.setFromValue_(frm)
    anim.setToValue_(to)
    anim.setDuration_(CROSSFADE_SEC)
    layer.setOpacity_(to)
    layer.addAnimation_forKey_(anim, "fade")


def _kitt_anim(frames, period):
    anim = CAKeyframeAnimation.animationWithKeyPath_("contents")
    anim.setValues_(frames)
    anim.setDuration_(period)
    anim.setCalculationMode_(kCAAnimationDiscrete)
    anim.setRepeatCount_(1e9)
    anim.setRemovedOnCompletion_(False)
    return anim


class Controller(NSObject):
    def check_(self, timer):
        try:
            screens = NSScreen.screens()
            for i, ent in enumerate(self.entries):
                if i < len(screens):
                    ent["panel"].setFrameOrigin_(top_center(screens[i].frame()))
            mode = KS.current_mode()
            if mode == self.mode:
                return
            self.mode = mode
            self.applyMode_(mode)
        except Exception:
            _log("check FAILED:\n" + traceback.format_exc())

    def applyMode_(self, mode):
        for ent in self.entries:
            a = ent["layers"][ent["active"]]
            b = ent["layers"][1 - ent["active"]]
            if mode is None:                         # wyłączone -> zgaś oba
                _fade(a, 0.0)
                _fade(b, 0.0)
                continue
            frames, period = self.cache[mode]
            b.setContents_(frames[0])
            b.removeAnimationForKey_("kitt")
            b.addAnimation_forKey_(_kitt_anim(frames, period), "kitt")
            _fade(b, 1.0)                             # nowy stan wchodzi...
            _fade(a, 0.0)                             # ...stary wychodzi
            ent["active"] = 1 - ent["active"]


def main():
    if not _single_instance():
        _log("inna instancja nakładki już działa — wychodzę")
        return

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    t0 = time.perf_counter()
    keepalive = []
    idle_frames, keep_i, _ = _build_frames("idle")
    speak_frames, keep_s, _ = _build_frames("speak")
    keepalive += [keep_i, keep_s]
    # „myśli" współdzieli klatki z idle — pojedyncza kropka, tylko szybciej.
    cache = {
        "idle": (idle_frames, _mode_period("idle")),
        "think": (idle_frames, _mode_period("think")),
        "speak": (speak_frames, _mode_period("speak")),
    }
    _log(f"prekompute {len(idle_frames) + len(speak_frames)} klatek w "
         f"{(time.perf_counter() - t0) * 1000:.0f} ms")

    entries = []
    for s in NSScreen.screens():
        panel, layers = make_panel()
        panel.setFrameOrigin_(top_center(s.frame()))
        entries.append({"panel": panel, "layers": layers, "active": 0})
    _log(f"start: {len(entries)} ekran(ów)")

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl.cache = cache
    ctrl._keepalive = keepalive
    ctrl.mode = "__none__"
    ctrl.check_(None)                            # ustaw tryb od razu
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        MODE_CHECK_SEC, ctrl, b"check:", None, True)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
