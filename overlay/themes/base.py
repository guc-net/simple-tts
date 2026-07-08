"""Baza motywów nakładki — czysta logika PIL + arytmetyka, zero Cocoa.

Motyw opisuje hostowi (kitt_overlay.py) trzy rzeczy:
  sprites() -> dict nazwa -> PIL.Image RGBA (host konwertuje raz do CGImage)
  layers()  -> płaska lista specyfikacji warstw {img,w,h,x,y,op} (pt)
  step()    -> aktualizacje (idx, "op"|"pos"|"img", wartość) na klatkę

Wspólne dla wszystkich motywów (implementowane tutaj):
  * kropki licznika sesji (fleet pips) — min(busy,5) kropek przy lewym brzegu,
    widoczne w trybach think/attention,
  * dirty-check (op/pos/img emitowane tylko przy realnej zmianie) + invalidate()
    wymuszający pełny zapis po wybudzeniu paneli,
  * pomocnicze sprite'y (świecąca kropka, ciemny pas) i wzór mrugania attention.

Tryby: idle | think | speak | attention. `snap` = {"busy": int, "age": sek}.
`level` (0..1) to wygładzona głośność mowy — liczy ją host z obwiedni.
"""

import math

from PIL import Image, ImageDraw

AMBER = (255, 176, 24)        # kolor trybu attention (wspólny język wizualny)
OP_EPS = 0.003                # mniejszych zmian krycia nie emitujemy

PIP_N = 5                     # maks. kropek licznika sesji
PIP_D = 5.0                   # średnica kropki (pt)
PIP_GAP = 9.0                 # rozstaw kropek (pt)
PIP_X0 = 10.0                 # środek pierwszej kropki od lewej (pt)
PIP_OP = 0.9

AGE_FULL_SEC = 900.0          # po 15 min pracy animacja osiąga pełne przyspieszenie
AGE_GAIN = 0.6                # maks. mnożnik tempa = 1 + AGE_GAIN


def glow_dot(px, color, boost=1.6):
    """Świecąca kropka RGBA: jasny środek, miękko gasnące krawędzie."""
    px = max(2, int(px))
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    p = img.load()
    r = px / 2.0
    for y in range(px):
        for x in range(px):
            nx, ny = (x - r) / r, (y - r) / r
            d = math.sqrt(nx * nx + ny * ny)
            if d >= 1.0:
                a = 0.0
            elif d <= 0.40:
                a = 1.0
            else:
                a = 1.0 - (d - 0.40) / 0.60
            a *= a
            p[x, y] = (color[0], color[1], color[2],
                       max(0, min(255, int(255 * a * boost))))
    return img


def dark_bar(w, h, alpha=0.14, color=(6, 6, 8)):
    """Delikatny półprzezroczysty ciemny pas (podkład) na całą listwę."""
    img = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, int(w) - 1, int(h) - 1],
                        radius=int(h * 0.30),
                        fill=(color[0], color[1], color[2], int(255 * alpha)))
    return img


def blink(now, period=1.2, pulses=((0.0, 0.14), (0.26, 0.40))):
    """Wzór mrugania attention: podwójny błysk, potem pauza. 0.0/1.0."""
    t = now % period
    for a, b in pulses:
        if a <= t < b:
            return 1.0
    return 0.0


def age_mult(age):
    """Mnożnik tempa animacji rosnący z czasem pracy (długa robota = nerwowiej)."""
    return 1.0 + AGE_GAIN * min(max(age, 0.0) / AGE_FULL_SEC, 1.0)


def ease_step(cur, target, dt, tau):
    """Jeden krok wykładniczego dążenia do celu — wspólny easing przejść.
    Zmiana trybu ustawia tylko CEL; wartość na ekranie zawsze płynie."""
    return cur + (target - cur) * (1.0 - math.exp(-dt / tau))


GATE_TAU = 0.30               # domyślne tempo bramek wjazdu/zjazdu efektów


class Theme:
    """Klasa bazowa. Podklasy implementują _sprites(), _layers(), _enter(), _step()."""

    FPS = {"idle": 21, "think": 21, "speak": 28, "attention": 21}
    PIP_COLOR = (255, 60, 30)

    def __init__(self, w, h, scale):
        self.w, self.h, self.scale = float(w), float(h), int(scale)
        self.mode = "idle"
        self.snap = {"busy": 0, "age": 0.0}
        self._applied = {}
        self._updates = []
        self._sprites_cache = None
        self._specs_cache = None
        self._pip_indices = []
        self._pip_cur = [0.0] * PIP_N

    # --- kontrakt hosta ------------------------------------------------------
    def sprites(self):
        if self._sprites_cache is None:
            spr = dict(self._sprites())
            spr["pip"] = glow_dot(PIP_D * self.scale, self.PIP_COLOR, boost=1.8)
            self._sprites_cache = spr
        return self._sprites_cache

    def layers(self):
        if self._specs_cache is None:
            specs = list(self._layers())
            first = len(specs)
            for i in range(PIP_N):
                specs.append({"img": "pip", "w": PIP_D, "h": PIP_D,
                              "x": PIP_X0 + i * PIP_GAP, "y": self.h / 2.0,
                              "op": 0.0})
            self._pip_indices = list(range(first, first + PIP_N))
            self._specs_cache = specs
        return self._specs_cache

    @property
    def pip_indices(self):
        self.layers()
        return self._pip_indices

    def enter_mode(self, mode, snap):
        self.layers()                      # upewnij się, że indeksy istnieją
        self.mode = mode
        self.snap = dict(snap)
        self._enter(mode)

    def step(self, dt, now, level, snap):
        self.layers()
        self.snap = dict(snap)
        self._updates = []
        self._step(dt, now, level)
        self._step_pips(dt)
        ups, self._updates = self._updates, []
        return ups

    def fps(self, mode):
        return self.FPS.get(mode, 21)

    def invalidate(self):
        """Po schowaniu paneli host traci stan warstw — następny step() ma
        zapisać wszystko od zera."""
        self._applied.clear()

    # --- emitery z dirty-checkiem (dla podklas) ------------------------------
    def op(self, idx, val):
        val = 0.0 if val < 0.0 else 1.0 if val > 1.0 else val
        key = ("op", idx)
        prev = self._applied.get(key)
        if prev is None or abs(val - prev) > OP_EPS or (val == 0.0 and prev != 0.0):
            self._applied[key] = val
            self._updates.append((idx, "op", val))

    def pos(self, idx, x, y):
        key = ("pos", idx)
        val = (round(x, 2), round(y, 2))
        if self._applied.get(key) != val:
            self._applied[key] = val
            self._updates.append((idx, "pos", val))

    def img(self, idx, sprite_key):
        key = ("img", idx)
        if self._applied.get(key) != sprite_key:
            self._applied[key] = sprite_key
            self._updates.append((idx, "img", sprite_key))

    # --- kropki licznika sesji ------------------------------------------------
    def _step_pips(self, dt):
        show = self.mode in ("think", "attention")
        lit = min(int(self.snap.get("busy", 0)), PIP_N) if show else 0
        for i, idx in enumerate(self._pip_indices):
            target = PIP_OP if i < lit else 0.0
            self._pip_cur[i] = ease_step(self._pip_cur[i], target, dt, 0.25)
            self.op(idx, self._pip_cur[i])

    # --- do nadpisania ---------------------------------------------------------
    def _sprites(self):
        raise NotImplementedError

    def _layers(self):
        raise NotImplementedError

    def _enter(self, mode):
        pass

    def _step(self, dt, now, level):
        raise NotImplementedError
