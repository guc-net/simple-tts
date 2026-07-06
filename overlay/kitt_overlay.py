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
  idle  -> wolny przejazd prawo<->lewo (myśli = szybciej); po IDLE_SLEEP_SEC
           ciągłego idle nakładka gaśnie i chowa się (jak None), budzi się
           dopiero gdy stan realnie się zmieni (nie przy samym upływie czasu)
  think -> kropka rozpędza się i przejeżdża prawo<->lewo (ogon gaśnie za nią)
  speak -> na środku, symetryczny rozbłysk w rytm głośności głosu (obwiednia)
  None  -> wygaszone (panel schodzi z ekranu, timer zwalnia do 1 s)

Wydajność (WindowServer to główny koszt overlayu, nie Python):
  * ZERO filtrów kompozycji (additionCompositing wymuszał offscreen rendering
    w WindowServerze przy każdej klatce) — zwykłe source-over,
  * cała statyka (ciemny pas + obudowy diod) wypalona w JEDEN obraz/warstwę,
  * dirty-check: setOpacity_ tylko gdy wartość realnie się zmieniła; klatka bez
    zmian nie otwiera nawet CATransaction (w ciszy speak: zero pracy),
  * po wygaszeniu panele są orderOut_ a szybki timer staje — zostaje wolny poll.

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
FPS_SWEEP = 21                 # przejazd idle/think — wolniejszy ruch, mniej klatek
FPS_SPEAK = 28                 # modulator mowy (obwiednia ma krok 0.04 s)
MODE_CHECK_SEC = 0.18
SCREEN_CHECK_SEC = 2.0
POLL_SEC = 1.0                 # wolny timer, gdy nakładka wygaszona
IDLE_SLEEP_SEC = 180.0         # ciągły idle dłużej niż to -> zgaśnij i schowaj się
N_LED = 13                     # dyskretne diody (jak segmenty w referencji)
EDGE = 22.0
FLOOR = 0.10                   # krycie zgaszonej diody (kropka ledwo się tli)
HEAD_BRIGHT = 1.0
HEAD_SIGMA = 0.07              # ile cel obejmuje świecąca głowa
CORE_THRESH = 0.55             # od jakiej jasności cela rozgrzewa się do bieli
BAR_ALPHA = 0.12               # krycie ciemnego pasa (wariant B — delikatny ślad)
CELL_ALPHA = 0.18              # krycie obudów diod (bez obrysów)
OP_EPS = 0.003                 # dirty-check: mniejszych zmian krycia nie wysyłamy
SWEEP_HALF = 0.44              # połowa szerokości przejazdu (0.5 = do krawędzi)
SPEED_IDLE = 0.30              # wolny przejazd w idle (myśli = szybszy)
SPEED_THINK = 0.52             # wolniejszy przejazd
EASE_TAU = 0.22                # wygładzenie dochodzenia do celu (przyspieszanie)
TAIL_TAU = 0.10                # krótszy ogon (szybciej znika)
SPEAK_TAU = 0.09               # spokojniejszy modulator (mniej migotania)
LEVEL_TAU = 0.07               # wygładzanie głośności w czasie (anty-migotanie)
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
# geometria celi (pt)
_SPACING = (W - 2 * EDGE) / (N_LED - 1)
CELL_W = _SPACING * 0.90
CELL_H = H * 0.72
GLOW_D = _SPACING * 0.86


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


def _cg(pil):
    w, h = pil.size
    raw = pil.tobytes()
    prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
    cg = CGImageCreate(w, h, 8, 32, w * 4, _CS,
                       kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                       prov, None, False, 0)
    return cg, raw


def _sprites():
    """CGImage poświaty, gorącej celi i statycznej listwy (+ bajty do utrzymania)."""
    glow, r1 = _cg(KF.dot_sprite(int(GLOW_D * SCALE), boost=1.5))
    hot, r2 = _cg(KF.hot_cell_sprite(int(CELL_W * SCALE), int(CELL_H * SCALE)))
    backing, r3 = _cg(KF.backing_sprite(
        W * SCALE, H * SCALE, [x * SCALE for x in _XS],
        CELL_W * SCALE, CELL_H * SCALE,
        bar_alpha=BAR_ALPHA, cell_alpha=CELL_ALPHA))
    return {"glow": glow, "hot": hot, "backing": backing}, [r1, r2, r3]


def _read_envelope():
    try:
        with open(SPEAK_STATE_PATH) as f:
            d = json.load(f)
        env, dt, start = d["env"], float(d["dt"]), float(d["start"])
        return (env, dt, start) if env else None
    except (OSError, ValueError, KeyError):
        return None


def _mk_layer(contents, w, h, x, y=_MIDY):
    lyr = CALayer.layer()
    lyr.setBounds_(((0.0, 0.0), (w, h)))
    lyr.setPosition_((x, y))
    lyr.setContentsGravity_("resize")
    lyr.setContentsScale_(SCALE)
    lyr.setContents_(contents)
    return lyr


def make_panel(spr):
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
    # statyka: ciemny pas + obudowy — jeden obraz, jedna warstwa, zero zmian
    container.addSublayer_(_mk_layer(spr["backing"], W, H, W / 2.0))
    glows, cores = [], []
    for x in _XS:                                   # poświata -> gorąca cela
        g = _mk_layer(spr["glow"], GLOW_D, GLOW_D, x)
        g.setOpacity_(FLOOR)
        container.addSublayer_(g)
        glows.append(g)
        c = _mk_layer(spr["hot"], CELL_W, CELL_H, x)
        c.setOpacity_(0.0)
        container.addSublayer_(c)
        cores.append(c)
    view.layer().addSublayer_(container)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, container, glows, cores


def top_center(sf):
    x = sf.origin.x + (sf.size.width - W) / 2.0
    y = sf.origin.y + sf.size.height - H - Y_OFFSET
    return x, y


class Controller(NSObject):
    def enterMode_(self, mode):
        self.speak = None
        if mode == "idle":
            self.idle_entered = time.monotonic()   # świeży start 3-minutowego licznika
        if mode is None:
            self.vis_t = 0.0
            return
        self.vis_t = 1.0
        if mode == "think":
            self.amp_t, self.speed_t, self.bloom_t = 1.0, SPEED_THINK, 0.0
        elif mode == "speak":
            self.amp_t, self.speed_t, self.bloom_t = 0.0, SPEED_IDLE, 1.0
            self.speak = _read_envelope()
        else:                                     # idle — wolny przejazd
            self.amp_t, self.speed_t, self.bloom_t = 1.0, SPEED_IDLE, 0.0

    # --- timery: szybki render <-> wolny poll po wygaszeniu -----------------
    def startFast(self):
        fps = FPS_SPEAK if self.mode == "speak" else FPS_SWEEP
        if self.fast_timer is not None and self.fast_fps == fps:
            return
        if self.slow_timer is not None:
            self.slow_timer.invalidate()
            self.slow_timer = None
        if self.fast_timer is not None:
            self.fast_timer.invalidate()
        else:
            self.t = time.monotonic()
        self.fast_fps = fps
        self.fast_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / fps, self, b"render:", None, True))
        self.fast_timer.setTolerance_(0.2 / fps)

    def startSlow(self):
        if self.slow_timer is not None:
            return
        if self.fast_timer is not None:
            self.fast_timer.invalidate()
            self.fast_timer = None
        self.slow_timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                POLL_SEC, self, b"poll:", None, True))
        self.slow_timer.setTolerance_(POLL_SEC * 0.2)

    def hidePanels(self):
        for ent in self.entries:
            ent["container"].setOpacity_(0.0)
            ent["panel"].orderOut_(None)
        self.applied_vis = 0.0
        self.led = [0.0] * N_LED
        self.applied_glow = [None] * N_LED        # wymuś pełny zapis po wybudzeniu
        self.applied_core = [None] * N_LED

    def poll_(self, timer):
        """Wygaszona nakładka: tylko sprawdzanie stanu, zero renderu.

        Budzi się, gdy stan realnie się zmienił względem tego, co ją uśpiło
        (self.sleep_mode) — dla wygaszenia po bezczynności to wciąż "idle"
        dopóki Claude nie zmieni stanu (a nie po prostu upływ czasu)."""
        try:
            m = KS.current_mode()
            if m == self.sleep_mode:
                return
            self.mode = m
            self.enterMode_(m)
            self.lastcheck = time.monotonic()
            self.reposition_(True)
            for ent in self.entries:
                ent["panel"].orderFrontRegardless()
            self.startFast()
        except Exception:
            _log("poll FAILED:\n" + traceback.format_exc())

    def reposition_(self, force):
        now = time.monotonic()
        if not force and now - self.lastscreens < SCREEN_CHECK_SEC:
            return
        self.lastscreens = now
        screens = NSScreen.screens()
        for i, ent in enumerate(self.entries):
            if i < len(screens):
                org = top_center(screens[i].frame())
                if org != ent.get("origin"):
                    ent["origin"] = org
                    ent["panel"].setFrameOrigin_(org)

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
                    self.startFast()          # speak = 28 fps, reszta 21
                self.reposition_(False)

            if self.mode == "idle" and now - self.idle_entered >= IDLE_SLEEP_SEC:
                self.vis_t = 0.0

            k = 1.0 - math.exp(-dt / EASE_TAU)
            self.amp += (self.amp_t - self.amp) * k
            self.speed += (self.speed_t - self.speed) * k
            self.vis += (self.vis_t - self.vis) * k
            if abs(self.vis - self.vis_t) < 0.004:
                self.vis = self.vis_t
            self.bloom += (self.bloom_t - self.bloom) * k
            self.phase += self.speed * dt
            hx = 0.5 + self.amp * SWEEP_HALF * _tri(self.phase)

            # wyciemnione do zera (KR wyłączony ALBO bezczynność > IDLE_SLEEP_SEC)
            # -> panele z ekranu, wolny poll; sleep_mode pamięta co uśpiło, żeby
            # poll_ wiedział, na jaką zmianę czekać (idle -> idle to nie zmiana)
            if self.vis_t == 0.0 and self.vis == 0.0:
                self.sleep_mode = self.mode
                self.hidePanels()
                self.startSlow()
                return

            if self.mode == "speak":
                if self.speak:
                    env, sdt, start = self.speak
                    idx = int((wall - start) / sdt)
                    level_t = env[idx] if 0 <= idx < len(env) else 0.0
                else:
                    level_t = 0.5 + 0.5 * math.sin(now * 6.0)
            else:
                level_t = 0.0
            self.level += (level_t - self.level) * (1.0 - math.exp(-dt / LEVEL_TAU))
            reach = (SPEAK_BASE + self.level * SPEAK_GAIN) * self.bloom
            decay = math.exp(-dt / (SPEAK_TAU if self.mode == "speak" else TAIL_TAU))
            led = self.led
            for i, p in enumerate(_POS):
                d = p - hx                          # modulator „rozkwita" wokół głowy
                head = HEAD_BRIGHT * math.exp(-(d / HEAD_SIGMA) ** 2)
                flare = _clamp((reach - abs(d)) / SPEAK_EDGE) * HEAD_BRIGHT
                des = head if head > flare else flare
                # afterglow: led co najmniej = bieżąca głowa, inaczej gaśnie z
                # poprzedniej wartości. max() zamiast if — inaczej przy des==led
                # led skakał des<->des*decay co klatkę (migotanie w spoczynku).
                led[i] = des if des > led[i] * decay else led[i] * decay
                if led[i] < 0.001:
                    led[i] = 0.0

            # dirty-check: wysyłamy tylko realne zmiany; brak zmian = brak transakcji
            ag, ac = self.applied_glow, self.applied_core
            updates = []
            for i, v in enumerate(led):
                go = FLOOR + (1.0 - FLOOR) * _clamp(v)
                co = _clamp((_clamp(v) - CORE_THRESH) / (1.0 - CORE_THRESH))
                if ag[i] is None or abs(go - ag[i]) > OP_EPS:
                    ag[i] = go
                    updates.append((i, 0, go))
                if ac[i] is None or abs(co - ac[i]) > OP_EPS \
                        or (co == 0.0 and ac[i] != 0.0):
                    ac[i] = co
                    updates.append((i, 1, co))
            vis_changed = self.vis != self.applied_vis
            if not updates and not vis_changed:
                return

            CATransaction.begin()
            CATransaction.setDisableActions_(True)
            for ent in self.entries:
                if vis_changed:
                    ent["container"].setOpacity_(self.vis)
                glows, cores = ent["glows"], ent["cores"]
                for i, which, val in updates:
                    (glows if which == 0 else cores)[i].setOpacity_(val)
            CATransaction.commit()
            self.applied_vis = self.vis
        except Exception:
            _log("render FAILED:\n" + traceback.format_exc())


def main():
    if not _single_instance():
        _log("inna instancja nakładki już działa — wychodzę")
        return

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    spr, keep = _sprites()
    entries = []
    for s in NSScreen.screens():
        panel, container, glows, cores = make_panel(spr)
        origin = top_center(s.frame())
        panel.setFrameOrigin_(origin)
        entries.append({"panel": panel, "container": container,
                        "glows": glows, "cores": cores, "origin": origin})
    _log(f"start (celki): {len(entries)} ekran(ów), {N_LED} diod")

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl._raw = keep
    ctrl.led = [FLOOR] * N_LED
    ctrl.applied_glow = [None] * N_LED
    ctrl.applied_core = [None] * N_LED
    ctrl.applied_vis = -1.0
    ctrl.mode = "__init__"
    ctrl.sleep_mode = None
    ctrl.idle_entered = time.monotonic()
    ctrl.speak = None
    ctrl.amp = ctrl.amp_t = 0.0
    ctrl.speed = ctrl.speed_t = SPEED_IDLE
    ctrl.vis = ctrl.vis_t = 0.0
    ctrl.bloom = ctrl.bloom_t = 0.0
    ctrl.level = 0.0
    ctrl.phase = 0.0
    ctrl.t = time.monotonic()
    ctrl.lastcheck = -1.0
    ctrl.lastscreens = -1.0
    ctrl.fast_timer = None
    ctrl.fast_fps = 0
    ctrl.slow_timer = None
    ctrl.startFast()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
