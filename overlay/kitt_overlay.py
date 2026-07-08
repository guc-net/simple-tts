#!/usr/bin/env python3
"""Nakładka simple-tts (Cocoa) — host motywów animacji na pasku menu.

Host odpowiada za wszystko, co wspólne: panele per ekran, timery (szybki
render <-> wolny poll po wygaszeniu), odczyt stanu (kitt_state.snapshot),
obwiednię mowy, płynne wygaszanie/budzenie i aplikowanie aktualizacji na
CALayer-ach. SAM WYGLĄD (sprite'y, warstwy, ruch) dostarcza motyw z themes/
(klucz `overlay_theme` w configu: kitt | cylon | hal | ekg | matrix | spark);
motyw można przełączać na żywo — host przebudowuje warstwy bez restartu.

Stany (kitt_state):
  idle      -> spokojna animacja; po IDLE_SLEEP_SEC ciągłego idle nakładka
               gaśnie i chowa się, budzi się gdy stan realnie się zmieni
  think     -> ktoś pracuje (żywsza animacja; motywy przyspieszają z wiekiem
               najstarszej roboty i pokazują kropki licznika sesji)
  speak     -> animacja w rytm głośności głosu (obwiednia z edge_speak)
  attention -> ktoś czeka na użytkownika (bursztynowe miganie)
  None      -> wygaszone (panel schodzi z ekranu, timer zwalnia do 1 s)

Wydajność: motywy emitują aktualizacje tylko przy realnej zmianie (dirty-check
w themes/base), klatka bez zmian nie otwiera nawet CATransaction; po wygaszeniu
panele są orderOut_ a szybki timer staje — zostaje wolny poll.

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
from themes import get_theme  # noqa: E402


# --- konfiguracja ----------------------------------------------------------
def _menubar_height(default=30.0):
    """Wysokość macowego paska menu (frame.maxY − visibleFrame.maxY). Listwa
    ma dokładnie tę wysokość, więc jej dolna krawędź wypada równo z dołem
    paska. Fallback, gdy ekranu nie da się odczytać."""
    try:
        s = NSScreen.mainScreen()
        f, vf = s.frame(), s.visibleFrame()
        h = (f.origin.y + f.size.height) - (vf.origin.y + vf.size.height)
        return h if h > 1 else default
    except Exception:
        return default


W = 520
H = int(round(_menubar_height()))   # listwa dokładnie na wysokość paska menu macOS
SCALE = 2
Y_OFFSET = 0                   # 0 = górna krawędź panelu równo z górą ekranu
MODE_CHECK_SEC = 0.18
SCREEN_CHECK_SEC = 2.0
POLL_SEC = 1.0                 # wolny timer, gdy nakładka wygaszona
IDLE_SLEEP_SEC = 60.0          # ciągły idle dłużej niż to -> zgaśnij i schowaj się
EASE_TAU = 0.22                # wygładzenie wygaszania/budzenia (krycie kontenera)
LEVEL_TAU = 0.07               # wygładzanie głośności w czasie (anty-migotanie)
LOG = os.path.expanduser("~/.claude/simple-tts-overlay.log")
LOCK_PATH = os.path.expanduser("~/.claude/simple-tts-overlay.lock")
SPEAK_STATE_PATH = os.path.expanduser("~/.claude/simple-tts-speak.json")

_CS = CGColorSpaceCreateDeviceRGB()
_lock_handle = None


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


def _cg(pil):
    w, h = pil.size
    raw = pil.tobytes()
    prov = CGDataProviderCreateWithData(None, raw, len(raw), None)
    cg = CGImageCreate(w, h, 8, 32, w * 4, _CS,
                       kCGImageAlphaLast | kCGBitmapByteOrderDefault,
                       prov, None, False, 0)
    return cg, raw


def _read_envelope():
    """Obwiednia mowy, którą edge_speak zapisuje tuż przed afplay. Odrzucamy
    NIEŚWIEŻĄ (już wybrzmiałą albo z przyszłości) — inaczej nakładka trzymałaby
    zamrożony modulator na starym pliku zamiast pokazać animację mowy.
    None => caller użyje syntetycznego modulatora (pulsowanie)."""
    try:
        with open(SPEAK_STATE_PATH) as f:
            d = json.load(f)
        env, dt, start = d["env"], float(d["dt"]), float(d["start"])
    except (OSError, ValueError, KeyError):
        return None
    if not env:
        return None
    age = time.time() - start
    if age < -0.5 or age > len(env) * dt + 0.5:   # z przyszłości albo wybrzmiała
        return None
    return (env, dt, start)


class OverlayPanel(NSPanel):
    # macOS domyślnie przycina okno tak, by jego górna krawędź nie weszła nad
    # pasek menu (constrainFrameRect:toScreen:). Zwracamy rect bez zmian, żeby
    # nakładka mogła usiąść NA pasku menu, na samej górze ekranu.
    def constrainFrameRect_toScreen_(self, frameRect, screen):
        return frameRect


def make_panel():
    """Pusty panel nakładki (warstwy dokłada _populate_container)."""
    panel = OverlayPanel.alloc().initWithContentRect_styleMask_backing_defer_(
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
    container.setMasksToBounds_(True)     # przewijane motywy (ekg/matrix) tną się na listwie
    container.setOpacity_(0.0)
    view.layer().addSublayer_(container)
    panel.setContentView_(view)
    panel.orderFrontRegardless()
    return panel, container


def top_center(sf):
    x = sf.origin.x + (sf.size.width - W) / 2.0
    y = sf.origin.y + sf.size.height - H - Y_OFFSET
    return x, y


class Controller(NSObject):
    # --- motyw ----------------------------------------------------------------
    def buildTheme_(self, name):
        """Zbuduj motyw + CGImage sprite'ów i wstaw jego warstwy do paneli."""
        theme = get_theme(name, W, H, SCALE)
        cgs, raws = {}, []
        for key, pil in theme.sprites().items():
            cg, raw = _cg(pil)
            cgs[key] = cg
            raws.append(raw)
        self.theme, self.theme_name = theme, name
        self.cgs, self._raw = cgs, raws
        self.specs = theme.layers()
        for ent in self.entries:
            self._populate_container(ent)
        theme.invalidate()

    def _populate_container(self, ent):
        container = ent["container"]
        container.setSublayers_(None)
        layers = []
        for spec in self.specs:
            lyr = CALayer.layer()
            lyr.setBounds_(((0.0, 0.0), (spec["w"], spec["h"])))
            lyr.setPosition_((spec["x"], spec["y"]))
            lyr.setContentsGravity_("resize")
            lyr.setContentsScale_(SCALE)
            lyr.setContents_(self.cgs[spec["img"]])
            lyr.setOpacity_(spec["op"])
            container.addSublayer_(lyr)
            layers.append(lyr)
        ent["layers"] = layers

    # --- stany -----------------------------------------------------------------
    def enterMode_(self, mode):
        self.speak = None
        if mode == "idle":
            self.idle_entered = time.monotonic()   # świeży start licznika uśpienia
        if mode is None:
            self.vis_t = 0.0
            return
        self.vis_t = 1.0
        if mode == "speak":
            self.speak = _read_envelope()
        self.theme.enter_mode(mode, self.snap)

    # --- timery: szybki render <-> wolny poll po wygaszeniu ---------------------
    def startFast(self):
        fps = self.theme.fps(self.mode) if self.mode else 21
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
        self.theme.invalidate()               # po wybudzeniu pełny zapis warstw

    def poll_(self, timer):
        """Wygaszona nakładka: tylko sprawdzanie stanu, zero renderu.

        Budzi się, gdy stan realnie się zmienił względem tego, co ją uśpiło
        (self.sleep_mode) — dla wygaszenia po bezczynności to wciąż "idle"
        dopóki Claude nie zmieni stanu (a nie po prostu upływ czasu)."""
        try:
            snap = KS.snapshot()
            if snap["mode"] == self.sleep_mode:
                return
            self.snap = snap
            self.mode = snap["mode"]
            self.enterMode_(self.mode)
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
                name = KS.theme_name()
                if name != self.theme_name:
                    _log(f"motyw: {self.theme_name} -> {name}")
                    self.buildTheme_(name)
                    self.theme.enter_mode(self.mode or "idle", self.snap)
                    self.startFast()          # nowy motyw może mieć inne fps
                snap = KS.snapshot()
                self.snap = snap
                if snap["mode"] != self.mode:
                    self.mode = snap["mode"]
                    self.enterMode_(self.mode)
                    self.startFast()          # fps zależne od motywu i trybu
                elif self.mode == "speak" and self.speak is None:
                    # obwiednia mogła się zapisać chwilę PO wejściu w speak
                    # (albo dogania fallback) — dociągnij ją, gdy się pojawi
                    self.speak = _read_envelope()
                self.reposition_(False)

            if self.mode == "idle" and now - self.idle_entered >= IDLE_SLEEP_SEC:
                self.vis_t = 0.0

            k = 1.0 - math.exp(-dt / EASE_TAU)
            self.vis += (self.vis_t - self.vis) * k
            if abs(self.vis - self.vis_t) < 0.004:
                self.vis = self.vis_t

            # wyciemnione do zera (nakładka wyłączona ALBO bezczynność) ->
            # panele z ekranu, wolny poll; sleep_mode pamięta co uśpiło, żeby
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

            updates = []
            if self.mode is not None:
                updates = self.theme.step(dt, now, self.level, self.snap)
            vis_changed = self.vis != self.applied_vis
            if not updates and not vis_changed:
                return

            CATransaction.begin()
            CATransaction.setDisableActions_(True)
            for ent in self.entries:
                if vis_changed:
                    ent["container"].setOpacity_(self.vis)
                layers = ent["layers"]
                for idx, prop, val in updates:
                    if prop == "op":
                        layers[idx].setOpacity_(val)
                    elif prop == "pos":
                        layers[idx].setPosition_(val)
                    else:                     # "img"
                        layers[idx].setContents_(self.cgs[val])
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

    entries = []
    for s in NSScreen.screens():
        panel, container = make_panel()
        origin = top_center(s.frame())
        panel.setFrameOrigin_(origin)
        entries.append({"panel": panel, "container": container,
                        "layers": [], "origin": origin})

    ctrl = Controller.alloc().init()
    ctrl.entries = entries
    ctrl.snap = {"mode": "idle", "busy": 0, "age": 0.0}
    ctrl.mode = "__init__"
    ctrl.theme_name = None
    ctrl.sleep_mode = None
    ctrl.idle_entered = time.monotonic()
    ctrl.speak = None
    ctrl.vis = ctrl.vis_t = 0.0
    ctrl.applied_vis = -1.0
    ctrl.level = 0.0
    ctrl.t = time.monotonic()
    ctrl.lastcheck = -1.0
    ctrl.lastscreens = -1.0
    ctrl.fast_timer = None
    ctrl.fast_fps = 0
    ctrl.slow_timer = None
    ctrl.buildTheme_(KS.theme_name())
    _log(f"start: {len(entries)} ekran(ów), motyw '{ctrl.theme_name}', "
         f"{len(ctrl.specs)} warstw")
    ctrl.mode = None
    ctrl.startFast()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log("FATAL:\n" + traceback.format_exc())
        raise
