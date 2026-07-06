#!/usr/bin/env python3
"""Nakładka KITT (Cocoa) dla simple-tts — nieruchomy rząd ledów, animowane krycie.

Model jak w prawdziwym KITT: ledy stoją w miejscu, a światło przebiega po nich i
KAŻDY gaśnie w miejscu po przejściu głowy (cienie zanikają, nie jadą). Każdy led
to CALayer; animujemy jego `opacity` (na GPU -> ~0% CPU).

Stany (kitt_state):
  idle   -> fala światła przebiega wolno prawo<->lewo, ledy za głową gasną
  think  -> to samo, szybciej (container.speed)
  speak  -> symetryczny rozbłysk od środka, szerokość/jasność w rytm głośności
            (obwiednia audio z simple-tts-speak.json) — mocno się rozszerza i zwęża
  None   -> wygaszone

Pływa nad pełnym ekranem (NSPanel + CanJoinAllSpaces + FullScreenAuxiliary),
pojedyncza instancja (flock). Wymaga: pyobjc Cocoa+Quartz, Pillow.
"""

import fcntl
import json
import math
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
    CAKeyframeAnimation,
    CALayer,
    CGColorSpaceCreateDeviceRGB,
    CGDataProviderCreateWithData,
    CGImageCreate,
    kCAAnimationLinear,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
)

# --- konfiguracja ----------------------------------------------------------
W, H = 520, 40
SCALE = 2
Y_OFFSET = 6
MODE_CHECK_SEC = 0.25
N_LED = 31                     # nieruchome ledy
EDGE = 16.0                    # margines na led po bokach
LED_D = 30                     # średnica świecenia leda (pt) — nachodzą = ciągły blask
HEAD_SIGMA = 0.035             # promień świecącej głowy-kropki (znormalizowany)
TAIL_LEN = 0.16                # długość gasnącego ogona ZA głową
FLOOR = 0.04                   # tło zgaszonego leda (blisko 0 = gaśnie)
IDLE_HALF = 1.8                # sekundy na jeden przejazd L->R
THINK_SPEEDUP = 2.6
BUILD_FPS = 30                 # gęstość klatek krycia (gładkość)
SPEAK_REACH_BASE = 0.04        # minimalny „rozstaw ust" (cisza)
SPEAK_REACH_GAIN = 0.40        # o ile rozszerza się przy pełnej głośności (mniej = węziej)
SPEAK_EDGE = 0.06              # miękkość krawędzi rozbłysku
DIP_SEC = 0.30                 # delikatne przygaszenie przy przełączaniu stanu
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")
LOCK_PATH = os.path.expanduser("~/.claude/simple-tts-overlay.lock")
SPEAK_STATE_PATH = os.path.expanduser("~/.claude/simple-tts-speak.json")

_CS = CGColorSpaceCreateDeviceRGB()
_lock_handle = None
_MIDY = H / 2.0
_POS = [i / (N_LED - 1) for i in range(N_LED)]           # znormalizowane 0..1
_XS = [EDGE + p * (W - 2 * EDGE) for p in _POS]           # x w punktach
_SWEEP_PERIOD = 2 * IDLE_HALF


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


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _led_cgimage():
    px = int(LED_D * SCALE)
    raw = KF.dot_sprite(px, boost=1.4).tobytes()
    prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
    cg = CGImageCreate(px, px, 8, 32, px * 4, _CS,
                       kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                       prov, None, False, 0)
    return cg, raw


# --- obliczanie krycia ledów (na GPU jako CAKeyframeAnimation opacity) ------
def _head(phase):
    """Pozycja głowy 0..1..0 (fala trójkątna) dla fazy 0..1."""
    return phase * 2.0 if phase < 0.5 else (1.0 - phase) * 2.0


def _sweep_opacity(p, phase):
    """Jasna głowa-kropka + ogon gasnący TYLKO za nią (kierunkowo). Przód ciemny."""
    h = _head(phase)
    direction = 1.0 if phase < 0.5 else -1.0        # 1. połowa w prawo, 2. w lewo
    behind = (h - p) * direction                    # >0: led jest ZA głową
    head = math.exp(-((p - h) / HEAD_SIGMA) ** 2)   # zwarta kropka
    tail = math.exp(-(behind / TAIL_LEN) ** 2) if behind >= 0 else 0.0
    return FLOOR + (1.0 - FLOOR) * max(head, tail)


def _sweep_anim(p):
    """Krycie jednego leda przez pełny okres przejazdu (bezszwowa pętla)."""
    n = max(2, int(_SWEEP_PERIOD * BUILD_FPS))
    vals = [_sweep_opacity(p, k / n) for k in range(n + 1)]   # k/n: 0..1, spójne
    a = CAKeyframeAnimation.animationWithKeyPath_("opacity")
    a.setValues_(vals)
    a.setDuration_(_SWEEP_PERIOD)
    a.setCalculationMode_(kCAAnimationLinear)
    a.setRepeatCount_(1e9)
    a.setRemovedOnCompletion_(False)
    return a


def _read_envelope():
    try:
        with open(SPEAK_STATE_PATH) as f:
            d = json.load(f)
        env, dt, start = d["env"], float(d["dt"]), float(d["start"])
        if not env:
            return None
        offset = time.time() - start
        if offset < 0 or offset >= len(env) * dt:
            return None
        return env, dt, offset
    except (OSError, ValueError, KeyError):
        return None


def _speak_opacity(p, level):
    """Symetryczny rozbłysk od środka; szerokość rośnie z głośnością `level`."""
    reach = SPEAK_REACH_BASE + level * SPEAK_REACH_GAIN
    lit = _clamp((reach - abs(p - 0.5)) / SPEAK_EDGE)
    return FLOOR + (1.0 - FLOOR) * lit


def _speak_anim(p, env, dt, offset):
    a = CAKeyframeAnimation.animationWithKeyPath_("opacity")
    a.setValues_([_speak_opacity(p, e) for e in env])
    a.setDuration_(len(env) * dt)
    a.setCalculationMode_(kCAAnimationLinear)
    a.setRemovedOnCompletion_(False)
    a.setTimeOffset_(offset)                     # sync do bieżącego miejsca audio
    return a


def _speak_pulse_anim(p):
    """Fallback bez obwiedni: żywy, symetryczny puls."""
    n = 24
    vals = [_speak_opacity(p, 0.5 + 0.5 * math.sin(2 * math.pi * k / n))
            for k in range(n + 1)]
    a = CAKeyframeAnimation.animationWithKeyPath_("opacity")
    a.setValues_(vals)
    a.setDuration_(0.9)
    a.setCalculationMode_(kCAAnimationLinear)
    a.setRepeatCount_(1e9)
    a.setRemovedOnCompletion_(False)
    return a


def _dip(container):
    """Delikatne przygaszenie przy przełączaniu stanu (jak w KITT)."""
    a = CAKeyframeAnimation.animationWithKeyPath_("opacity")
    a.setValues_([1.0, 0.35, 1.0])
    a.setKeyTimes_([0.0, 0.45, 1.0])
    a.setDuration_(DIP_SEC)
    a.setRemovedOnCompletion_(True)
    container.setOpacity_(1.0)
    container.addAnimation_forKey_(a, "dip")


def _fade(container, to):
    a = CAKeyframeAnimation.animationWithKeyPath_("opacity")
    pl = container.presentationLayer()
    frm = pl.opacity() if pl is not None else container.opacity()
    a.setValues_([frm, to])
    a.setDuration_(DIP_SEC)
    a.setRemovedOnCompletion_(True)
    container.setOpacity_(to)
    container.addAnimation_forKey_(a, "fade")


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
    container = CALayer.layer()
    container.setFrame_(NSMakeRect(0, 0, W, H))
    container.setOpacity_(0.0)
    leds = []
    for x in _XS:
        led = CALayer.layer()
        led.setBounds_(((0.0, 0.0), (LED_D, LED_D)))
        led.setPosition_((x, _MIDY))
        led.setContentsGravity_("resizeAspect")
        led.setContentsScale_(SCALE)
        led.setContents_(cgimg)
        led.setOpacity_(FLOOR)
        container.addSublayer_(led)
        leds.append(led)
    view.layer().addSublayer_(container)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, container, leds


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
            container, leds = ent["container"], ent["leds"]
            if mode is None:
                _fade(container, 0.0)
                continue
            if old is None or old == "__init__":
                _fade(container, 1.0)
            else:
                _dip(container)                  # przygaszenie „po przełączeniu"

            if mode in ("idle", "think"):
                container.setSpeed_(THINK_SPEEDUP if mode == "think" else 1.0)
                if old not in ("idle", "think"):
                    for i, led in enumerate(leds):
                        led.addAnimation_forKey_(self.sweep[i], "op")
            else:                                # speak
                container.setSpeed_(1.0)
                data = _read_envelope()
                for i, led in enumerate(leds):
                    if data:
                        env, dt, off = data
                        anim = _speak_anim(_POS[i], env, dt, off)
                    else:
                        anim = _speak_pulse_anim(_POS[i])
                    led.addAnimation_forKey_(anim, "op")


def main():
    if not _single_instance():
        _log("inna instancja nakładki już działa — wychodzę")
        return

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    cgimg, raw = _led_cgimage()
    sweep = [_sweep_anim(p) for p in _POS]       # animacje przejazdu (raz)

    entries = []
    for s in NSScreen.screens():
        panel, container, leds = make_panel(cgimg)
        panel.setFrameOrigin_(top_center(s.frame()))
        entries.append({"panel": panel, "container": container, "leds": leds})
    _log(f"start (LED): {len(entries)} ekran(ów), {N_LED} ledów")

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl.sweep = sweep
    ctrl.curmode = "__none__"
    ctrl.prevmode = "__init__"
    ctrl._raw = raw
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
