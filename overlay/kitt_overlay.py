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
    kCAAnimationDiscrete,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
)

W, H = 520, 40             # rozmiar w punktach
SCALE = 2                  # render 2x (Retina)
Y_OFFSET = 6               # od górnej krawędzi ekranu
MODE_CHECK_SEC = 0.25      # jak często sprawdzać stan (jedyny timer)
BUILD_FPS = 16             # gęstość klatek w prekompute
ALPHA_BOOST = 2.2          # krycie: jaśniej = bardziej kryjące
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")

_CS = CGColorSpaceCreateDeviceRGB()


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
        return 2 * math.pi / 6.2             # okres sin(t*6.2)
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
    layer = CALayer.layer()
    layer.setFrame_(NSMakeRect(0, 0, W, H))
    layer.setContentsGravity_("resize")
    layer.setContentsScale_(SCALE)
    view.layer().addSublayer_(layer)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, layer


def top_center(screen_frame):
    x = screen_frame.origin.x + (screen_frame.size.width - W) / 2.0
    y = screen_frame.origin.y + screen_frame.size.height - H - Y_OFFSET
    return x, y


class Controller(NSObject):
    def check_(self, timer):
        try:
            screens = NSScreen.screens()
            for i, (panel, _layer) in enumerate(self.panels):
                if i < len(screens):
                    panel.setFrameOrigin_(top_center(screens[i].frame()))
            mode = KS.current_mode()
            if mode == self.mode:
                return
            self.mode = mode
            self.applyMode_(mode)
        except Exception:
            _log("check FAILED:\n" + traceback.format_exc())

    def applyMode_(self, mode):
        if mode is None:                         # tryb wyłączony -> nic
            for _panel, layer in self.panels:
                layer.removeAnimationForKey_("kitt")
                layer.setContents_(None)
            return
        frames, period = self.cache[mode]
        for _panel, layer in self.panels:
            layer.setContents_(frames[0])
            anim = CAKeyframeAnimation.animationWithKeyPath_("contents")
            anim.setValues_(frames)
            anim.setDuration_(period)
            anim.setCalculationMode_(kCAAnimationDiscrete)
            anim.setRepeatCount_(1e9)
            anim.setRemovedOnCompletion_(False)
            layer.removeAnimationForKey_("kitt")
            layer.addAnimation_forKey_(anim, "kitt")


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    t0 = time.perf_counter()
    cache, keepalive = {}, []
    for mode in ("idle", "think", "speak"):
        frames, keep, period = _build_frames(mode)
        cache[mode] = (frames, period)
        keepalive.append(keep)                   # utrzymaj bajty CGImage żywe
    _log(f"prekompute {sum(len(cache[m][0]) for m in cache)} klatek w "
         f"{(time.perf_counter() - t0) * 1000:.0f} ms")

    panels = [make_panel() for _ in NSScreen.screens()]
    for (panel, _layer), s in zip(panels, NSScreen.screens()):
        panel.setFrameOrigin_(top_center(s.frame()))
    _log(f"start: {len(panels)} ekran(ów)")

    ctrl = Controller.alloc().init()
    ctrl.panels = panels
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
