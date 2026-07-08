"""Motyw Matrix — cyfrowy deszcz w listwie.

Kolumny pseudo-glifów (deterministyczne, seedowany Random) suną w dół; każda
ma własną prędkość i pasek sprite'a wybrany z kilku wariantów. Tryb steruje
gęstością (kryciem) i tempem:

  idle      -> rzadki, powolny deszcz
  think     -> pełna gęstość; przyspiesza z wiekiem roboty
  speak     -> jasność pulsuje w rytm głosu
  attention -> deszcz przechodzi w bursztyn i mruga
"""

import random

from PIL import Image, ImageDraw

from .base import AMBER, Theme, age_mult, blink, ease_step

GREEN = (64, 255, 120)
HEAD = (210, 255, 220)
N_VARIANTS = 4
STRIP_W = 13.0                # szerokość kolumny (pt)
STRIP_REPEAT = 3              # pasek ma 3 wysokości listwy (zapętlany)
SPEED_MULT = {"idle": 0.45, "think": 1.0, "speak": 1.25, "attention": 1.1}
BASE_OP = {"idle": 0.28, "think": 0.75, "speak": 0.55, "attention": 0.85}


def _glyph(d, x, y, cell, rng, color, width):
    """Pseudo-glif: 3-5 krótkich kresek w komórce (czytelne jako 'znaki'
    przy wysokości listwy, bez zależności od fontów)."""
    for _ in range(rng.randint(3, 5)):
        x0 = x + rng.uniform(0.05, 0.55) * cell
        y0 = y + rng.uniform(0.05, 0.65) * cell
        if rng.random() < 0.5:
            d.line([x0, y0, x0 + rng.uniform(0.25, 0.55) * cell, y0],
                   fill=color, width=width)
        else:
            d.line([x0, y0, x0, y0 + rng.uniform(0.25, 0.6) * cell],
                   fill=color, width=width)


def strip_sprite(w_px, h_px, seed, base_color):
    """Pionowy pasek glifów z jaśniejszą 'głową' co jakiś czas i gasnącym
    ogonem — przewijany w pionie daje efekt deszczu."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (int(w_px), int(h_px)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cell = w_px * 0.55                           # gęsty deszcz: ~2 glify na szerokość
    stroke = max(1, int(cell * 0.14))
    n = max(6, int(h_px / cell))
    head_at = rng.randrange(n)
    for i in range(n):
        y = i * cell
        dist = (i - head_at) % n
        bright = 1.0 if dist == 0 else max(0.30, 1.0 - dist / (n * 0.9))
        if rng.random() < 0.10 and dist != 0:
            continue                             # dziura w kolumnie
        c = HEAD if dist == 0 else base_color
        a = int(255 * bright)
        _glyph(d, 1, y, cell, rng, (c[0], c[1], c[2], a), stroke)
    return img


class MatrixTheme(Theme):
    FPS = {"idle": 18, "think": 24, "speak": 26, "attention": 24}
    PIP_COLOR = GREEN

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        rng = random.Random(42)
        self.n_cols = max(8, int(w / 21.0))
        margin = STRIP_W / 2.0 + 2.0
        span = w - 2 * margin
        self.col_x = [margin + span * i / (self.n_cols - 1)
                      + rng.uniform(-2.0, 2.0) for i in range(self.n_cols)]
        self.col_speed = [rng.uniform(18.0, 44.0) for _ in range(self.n_cols)]
        self.col_var = [rng.randrange(N_VARIANTS) for _ in range(self.n_cols)]
        self.col_off = [rng.uniform(0, h * STRIP_REPEAT)
                        for _ in range(self.n_cols)]
        # zmiana palety: kolumny przebarwiają się jedna po drugiej (fala),
        # każda po swoim losowym opóźnieniu od zmiany trybu
        self.col_delay = [rng.uniform(0.05, 1.5) for _ in range(self.n_cols)]
        self.col_amber = [False] * self.n_cols
        self.pal_elapsed = 0.0
        self.pal_target = False
        self.cur_op = BASE_OP["idle"]
        self.cur_mult = SPEED_MULT["idle"]

    def _sprites(self):
        s = self.scale
        w_px = int(STRIP_W * s)
        h_px = int(self.h * STRIP_REPEAT * s)
        spr = {}
        for v in range(N_VARIANTS):
            spr[f"strip{v}"] = strip_sprite(w_px, h_px, 100 + v, GREEN)
            spr[f"astrip{v}"] = strip_sprite(w_px, h_px, 100 + v, AMBER)
        return spr

    def _layers(self):
        # dwie kafle paska na kolumnę (bezszwowy przewijany marquee w pionie)
        sh = self.h * STRIP_REPEAT
        specs = []
        for i in range(self.n_cols):
            for _ in range(2):
                specs.append({"img": f"strip{self.col_var[i]}",
                              "w": STRIP_W, "h": sh,
                              "x": self.col_x[i], "y": self.h / 2.0,
                              "op": BASE_OP["idle"]})
        return specs

    def _enter(self, mode):
        pass                                     # deszcz płynie ciągle

    def _step(self, dt, now, level):
        mode = self.mode if self.mode in SPEED_MULT else "idle"
        mult_t = SPEED_MULT[mode]
        if mode == "think":
            mult_t *= age_mult(self.snap.get("age", 0.0))
        amber = mode == "attention"
        op_t = BASE_OP[mode]
        if mode == "speak":
            op_t = 0.35 + 0.55 * level
        elif amber:
            op_t *= 0.55 + 0.45 * blink(now, period=1.2,
                                        pulses=((0.0, 0.30), (0.5, 0.80)))
        # tempo i krycie płyną do celów trybu zamiast skakać
        self.cur_mult = ease_step(self.cur_mult, mult_t, dt, 0.5)
        self.cur_op = ease_step(self.cur_op, op_t, dt, 0.4)

        # fala przebarwienia: licznik od zmiany docelowej palety
        if amber != self.pal_target:
            self.pal_target = amber
            self.pal_elapsed = 0.0
        self.pal_elapsed += dt

        period = self.h * STRIP_REPEAT
        for i in range(self.n_cols):
            self.col_off[i] = (self.col_off[i]
                               + self.col_speed[i] * self.cur_mult * dt) % period
            # kafle suną w dół; druga zawsze o wysokość paska wyżej
            ya = self.h / 2.0 - self.col_off[i]
            a, b = 2 * i, 2 * i + 1
            self.pos(a, self.col_x[i], ya)
            self.pos(b, self.col_x[i], ya + period)
            if self.col_amber[i] != self.pal_target \
                    and self.pal_elapsed >= self.col_delay[i]:
                self.col_amber[i] = self.pal_target
            prefix = "astrip" if self.col_amber[i] else "strip"
            key = f"{prefix}{self.col_var[i]}"
            for idx in (a, b):
                self.img(idx, key)
                self.op(idx, self.cur_op)
