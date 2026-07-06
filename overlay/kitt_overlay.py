#!/usr/bin/env python3
"""Nakładka KITT (Cocoa) dla simple-tts — ciągła symulacja świateł.

Jedna spójna symulacja klatka-po-klatce (nie osobne animacje per stan):
  * głowa ma PŁYNNIE animowaną pozycję (amplituda i prędkość dochodzą do
    docelowych wartości z wygładzeniem) — więc kropka płynnie przesuwa się i
    PRZYSPIESZA między stanami, bez skoków; przejścia to jedno płynne działanie,
  * ogon powstaje z WYGASANIA ledów w miejscu (afterglow) — cienie zanikają
    tam, gdzie są, nie jadą,
  * ledy stoją w miejscu; sterujemy tylko ich kryciem.

Stany (kitt_state):
  idle  -> jasna kropka spoczywa na środku
  think -> kropka rozpędza się i przejeżdża prawo<->lewo (ogon gaśnie za nią)
  speak -> na środku, symetryczny rozbłysk w rytm głośności głosu (obwiednia)
  None  -> wygaszone

Pływa nad pełnym ekranem, pojedyncza instancja. Wymaga pyobjc Cocoa+Quartz, Pillow.
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
    CALayer,
    CATransaction,
    CGColorSpaceCreateDeviceRGB,
    CGDataProviderCreateWithData,
    CGImageCreate,
    kCGBitmapByteOrderDefault,
    kCGImageAlphaLast,
)

# --- konfiguracja ----------------------------------------------------------
W, H = 520, 40
SCALE = 2
Y_OFFSET = 6
RENDER_FPS = 40
MODE_CHECK_SEC = 0.18
N_LED = 31
EDGE = 16.0
LED_D = 30
FLOOR = 0.03                   # krycie zgaszonego leda
HEAD_BRIGHT = 1.0
HEAD_SIGMA = 0.045             # promień jasnej głowy (znormalizowany)
SWEEP_HALF = 0.44              # połowa szerokości przejazdu (0.5 = do krawędzi)
SPEED_IDLE = 0.25              # tempo fazy w spoczynku (i tak amp=0)
SPEED_THINK = 0.85             # tempo przejazdu w „myśli"
EASE_TAU = 0.22                # wygładzenie dochodzenia do celu (przyspieszanie)
TAIL_TAU = 0.16                # czas wygasania ogona (dłużej = dłuższy ogon)
SPEAK_TAU = 0.05               # szybkie wygasanie w modulatorze (czułość)
SPEAK_BASE = 0.03              # min. rozstaw modulatora (cisza)
SPEAK_GAIN = 0.34              # rozszerzanie z głośnością
SPEAK_EDGE = 0.06              # miękkość krawędzi rozbłysku
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")
LOCK_PATH = os.path.expanduser("~/.claude/simple-tts-overlay.lock")
SPEAK_STATE_PATH = os.path.expanduser("~/.claude/simple-tts-speak.json")

_CS = CGColorSpaceCreateDeviceRGB()
_lock_handle = None
_MIDY = H / 2.0
_POS = [i / (N_LED - 1) for i in range(N_LED)]
_XS = [EDGE + p * (W - 2 * EDGE) for p in _POS]


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


def _tri(phase):
    ph = phase % 1.0
    return 1.0 - 4.0 * abs(ph - 0.5)          # -1 .. +1 .. -1


def _led_cgimage():
    px = int(LED_D * SCALE)
    raw = KF.dot_sprite(px, boost=1.6).tobytes()
    prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
    cg = CGImageCreate(px, px, 8, 32, px * 4, _CS,
                       kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                       prov, None, False, 0)
    return cg, raw


def _read_envelope():
    try:
        with open(SPEAK_STATE_PATH) as f:
            d = json.load(f)
        env, dt, start = d["env"], float(d["dt"]), float(d["start"])
        return (env, dt, start) if env else None
    except (OSError, ValueError, KeyError):
        return None


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
        led.setCompositingFilter_("additionCompositing")   # blask się sumuje
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
    def enterMode_(self, mode):
        self.speak = None
        if mode is None:
            self.vis_t = 0.0
            return
        self.vis_t = 1.0
        if mode == "think":
            self.amp_t, self.speed_t, self.bloom_t = 1.0, SPEED_THINK, 0.0
        elif mode == "speak":
            self.amp_t, self.speed_t, self.bloom_t = 0.0, SPEED_IDLE, 1.0
            self.speak = _read_envelope()
        else:                                     # idle
            self.amp_t, self.speed_t, self.bloom_t = 0.0, SPEED_IDLE, 0.0

    def render_(self, timer):
        try:
            now = time.monotonic()
            dt = min(0.1, now - self.t)
            self.t = now
            wall = time.time()

            if now - self.lastcheck >= MODE_CHECK_SEC:
                self.lastcheck = now
                m = KS.current_mode()
                if m != self.mode:
                    self.mode = m
                    self.enterMode_(m)
                screens = NSScreen.screens()
                for i, ent in enumerate(self.entries):
                    if i < len(screens):
                        ent["panel"].setFrameOrigin_(top_center(screens[i].frame()))

            k = 1.0 - math.exp(-dt / EASE_TAU)
            self.amp += (self.amp_t - self.amp) * k
            self.speed += (self.speed_t - self.speed) * k
            self.vis += (self.vis_t - self.vis) * k
            self.bloom += (self.bloom_t - self.bloom) * k
            self.phase += self.speed * dt
            hx = 0.5 + self.amp * SWEEP_HALF * _tri(self.phase)

            if self.mode == "speak":
                if self.speak:
                    env, sdt, start = self.speak
                    idx = int((wall - start) / sdt)
                    level = env[idx] if 0 <= idx < len(env) else 0.0
                else:
                    level = 0.5 + 0.5 * math.sin(now * 6.0)
            else:
                level = 0.0
            reach = (SPEAK_BASE + level * SPEAK_GAIN) * self.bloom
            decay = math.exp(-dt / (SPEAK_TAU if self.mode == "speak" else TAIL_TAU))
            led = self.led
            for i, p in enumerate(_POS):
                d = p - hx                          # modulator „rozkwita" wokół głowy
                head = HEAD_BRIGHT * math.exp(-(d / HEAD_SIGMA) ** 2)
                flare = _clamp((reach - abs(d)) / SPEAK_EDGE) * HEAD_BRIGHT
                des = head if head > flare else flare
                led[i] = des if des > led[i] else led[i] * decay

            CATransaction.begin()
            CATransaction.setDisableActions_(True)
            vis = self.vis
            out = [FLOOR + (1.0 - FLOOR) * _clamp(v) for v in led]
            for ent in self.entries:
                ent["container"].setOpacity_(vis)
                lyrs = ent["leds"]
                for i in range(N_LED):
                    lyrs[i].setOpacity_(out[i])
            CATransaction.commit()
        except Exception:
            _log("render FAILED:\n" + traceback.format_exc())


def main():
    if not _single_instance():
        _log("inna instancja nakładki już działa — wychodzę")
        return

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    cgimg, raw = _led_cgimage()
    entries = []
    for s in NSScreen.screens():
        panel, container, leds = make_panel(cgimg)
        panel.setFrameOrigin_(top_center(s.frame()))
        entries.append({"panel": panel, "container": container, "leds": leds})
    _log(f"start (sim): {len(entries)} ekran(ów), {N_LED} ledów")

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl._raw = raw
    ctrl.led = [FLOOR] * N_LED
    ctrl.mode = "__init__"
    ctrl.speak = None
    ctrl.amp = ctrl.amp_t = 0.0
    ctrl.speed = ctrl.speed_t = SPEED_IDLE
    ctrl.vis = ctrl.vis_t = 0.0
    ctrl.bloom = ctrl.bloom_t = 0.0
    ctrl.phase = 0.0
    ctrl.t = time.monotonic()
    ctrl.lastcheck = -1.0
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0 / RENDER_FPS, ctrl, b"render:", None, True)
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
