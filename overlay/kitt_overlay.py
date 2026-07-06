#!/usr/bin/env python3
"""Nakładka KITT (Cocoa) dla simple-tts — pływa NAD pełnoekranowym terminalem.

Trzy tryby wg stanu simple-tts (patrz kitt_state):
  idle  -> kropka + gasnący ogon jeździ prawo<->lewo
  think -> dwie kropki nerwowo gonią się (Claude pracuje)
  speak -> modulator głosu (simple-tts właśnie mówi)

Przezroczyste, klik-przechodzące NSPanel na każdym ekranie, na wysokim poziomie
z CanJoinAllSpaces + FullScreenAuxiliary, więc widać je też na Spejsie aplikacji
pełnoekranowej. Wymaga: pyobjc-framework-Cocoa, Pillow.

Uruchamiać pythonem z tymi zależnościami (patrz install_overlay.sh).
"""

import io
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
    NSImage,
    NSImageScaleAxesIndependently,
    NSImageView,
    NSPanel,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSData, NSMakeRect, NSObject, NSTimer  # noqa: E402

W, H = 520, 40             # rozmiar w punktach
SCALE = 2                  # render 2x (Retina)
Y_OFFSET = 6               # od górnej krawędzi ekranu
FPS = 16
MODE_CHECK_SEC = 0.20      # jak często sprawdzać stan (rzadziej niż render)
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")


def _log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def pil_to_nsimage(pil_img):
    buf = io.BytesIO()
    pil_img.save(buf, "PNG")
    raw = buf.getvalue()
    return NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(raw, len(raw)))


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
    iv = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
    iv.setImageScaling_(NSImageScaleAxesIndependently)
    panel.setContentView_(iv)
    panel.orderFrontRegardless()
    return panel, iv


def top_center(screen_frame):
    x = screen_frame.origin.x + (screen_frame.size.width - W) / 2.0
    y = screen_frame.origin.y + screen_frame.size.height - H - Y_OFFSET
    return x, y


class Ticker(NSObject):
    def tick_(self, timer):
        try:
            now = time.monotonic()
            if now - self.last_check >= MODE_CHECK_SEC:
                self.last_check = now
                self.mode = KS.current_mode()
            if self.mode is None:                      # nakładka wyłączona
                for _, iv in self.panels:
                    iv.setImage_(None)
                return
            t = now - self.start
            frame = KF.render(W * SCALE, H * SCALE, t, self.mode)
            alpha = frame.convert("L").point(lambda v: min(255, int(v * 2.2)))
            rgba = frame.convert("RGBA")
            rgba.putalpha(alpha)
            nsimg = pil_to_nsimage(rgba)
            screens = NSScreen.screens()
            for i, (panel, iv) in enumerate(self.panels):
                if i < len(screens):
                    panel.setFrameOrigin_(top_center(screens[i].frame()))
                iv.setImage_(nsimg)
        except Exception:
            _log("tick FAILED:\n" + traceback.format_exc())


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    panels = []
    for s in NSScreen.screens():
        panel, iv = make_panel()
        panel.setFrameOrigin_(top_center(s.frame()))
        panels.append((panel, iv))
    _log(f"start: {len(panels)} ekran(ów)")

    ticker = Ticker.alloc().init()
    ticker.panels = panels
    ticker.start = time.monotonic()
    ticker.last_check = -1.0
    ticker.mode = "idle"
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0 / FPS, ticker, b"tick:", None, True)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
