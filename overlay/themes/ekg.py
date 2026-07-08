"""Motyw EKG — monitor pracy serca przewijany jak papier milimetrowy.

Ślad to TAŚMOCIĄG krótkich segmentów (w_seg = pół listwy): segment wjeżdża
z prawej wyrenderowany dla trybu obowiązującego w chwili wjazdu, a po zjechaniu
z lewej jest zawracany na prawy koniec z nowym wariantem. Dzięki temu zmiana
trybu NIGDY nie przerysowuje widocznego zapisu — stare bicia dojeżdżają do
lewej krawędzi i znikają, a nowy rytm (inna częstość, amplituda, kolor) po
prostu wjeżdża za nimi; zmienia się też płynnie tempo papieru (easing).

Segmenty mają po kilka wariantów na tryb (jitter RR, inna amplituda każdego
uderzenia, falująca izolinia wygaszana przy krawędziach segmentu — sąsiednie
segmenty łączą się na izolinii bez uskoku):

  idle      -> prawie płaska izolinia z rzadkim, drobnym załamkiem
  think     -> spokojny rytm zatokowy; tętno rośnie z wiekiem roboty
  speak     -> gęsty, ostry zapis + kropka pulsująca w rytm głosu
  attention -> bursztynowy, nerwowy zapis (częstoskurcz) + mrugająca kropka
"""

import math
import random

from PIL import Image, ImageDraw

from .base import (
    AMBER,
    GATE_TAU,
    Theme,
    age_mult,
    blink,
    dark_bar,
    ease_step,
    glow_dot,
)

GREEN = (57, 255, 106)
N_VARIANTS = 3                # warianty segmentu per tryb (przeciw powtarzalności)
SEG_FRAC = 0.5                # segment = pół szerokości listwy
N_SEG = 3                     # tyle segmentów wystarcza na pokrycie listwy + zapas

# tryb -> (zakres uderzeń na segment, amplituda, seed wariantów)
BEATS = {
    "idle": ((0, 1), 0.35, 11),
    "think": ((1, 2), 1.0, 23),
    "speak": ((2, 3), 1.0, 37),
    "attention": ((2, 3), 1.0, 53),
}
SPEED = {"idle": 26.0, "think": 55.0, "speak": 85.0, "attention": 95.0}
SPEED_TAU = 0.6               # wygładzenie zmiany tempa papieru (s)


def _beat_points(cx, amp, rng):
    """Punkty jednego uderzenia PQRST wokół środka cx — każde odrobinę inne
    (amplituda R, głębokość S, wysokość T i szerokości losowane per uderzenie)."""
    a = amp * rng.uniform(0.82, 1.08)
    r_w = rng.uniform(2.4, 3.6)
    p_h = 0.12 * a * rng.uniform(0.6, 1.3)
    q_d = -0.14 * a * rng.uniform(0.7, 1.2)
    s_d = -0.30 * a * rng.uniform(0.7, 1.25)
    t_h = 0.22 * a * rng.uniform(0.7, 1.4)
    t_x = rng.uniform(14.0, 20.0)
    return [
        (cx - 26, 0.0), (cx - 20, p_h), (cx - 14, 0.0),          # P
        (cx - 2 * r_w, 0.0), (cx - r_w, q_d),                    # Q
        (cx, 0.95 * a),                                          # R
        (cx + r_w, s_d), (cx + 2 * r_w, 0.0),                    # S
        (cx + t_x, 0.0), (cx + t_x + 7, t_h), (cx + t_x + 14, 0.0),   # T
    ]


def _wander(w, rng, cycles=(1, 2, 4), amps=(0.045, 0.030, 0.015)):
    """Dryf izolinii: suma sinusoid o losowych fazach, wygaszana do zera przy
    krawędziach segmentu (okno smoothstep) — segmenty sklejają się na izolinii."""
    phases = [rng.uniform(0, 2 * math.pi) for _ in cycles]
    edge = w * 0.12

    def f(x):
        v = sum(a * math.sin(2 * math.pi * k * x / w + p)
                for k, a, p in zip(cycles, amps, phases))
        t = min(x, w - x) / edge
        if t < 1.0:
            t = max(0.0, t)
            v *= t * t * (3.0 - 2.0 * t)         # smoothstep do 0 na krawędzi
        return v

    return f


def segment_tile(w, h, beats_range, amp, seed, color):
    """Segment śladu EKG (RGBA, w×h px): falująca izolinia + losowa liczba
    uderzeń o jitterowanych pozycjach. Zaczyna i kończy na izolinii."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base_y = h * 0.58
    span = h * 0.40
    wander = _wander(w, rng)

    margin = 44.0
    n_beats = rng.randint(*beats_range)
    centers = []
    for b in range(n_beats):
        c = w * (b + 0.5) / max(1, n_beats) \
            + rng.uniform(-0.18, 0.18) * w / max(1, n_beats)
        centers.append(min(w - margin, max(margin, c)))
    beat_pts = [_beat_points(c, amp, rng) for c in centers]

    def beat_shape(x):
        for pts in beat_pts:
            if pts[0][0] <= x <= pts[-1][0]:
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    if x0 <= x <= x1:
                        t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                        return y0 + (y1 - y0) * t
        return 0.0

    xs = set(float(x) for x in range(0, int(w) + 1, 3))
    for pts in beat_pts:
        xs.update(x for x, _ in pts)
    xy = [(x, base_y - (wander(x) + beat_shape(x)) * span)
          for x in sorted(xs)]

    glow = tuple(color) + (70,)
    core = tuple(color) + (255,)
    d.line(xy, fill=glow, width=max(3, int(h * 0.10)), joint="curve")
    d.line(xy, fill=core, width=max(1, int(h * 0.035)), joint="curve")
    return img


class EkgTheme(Theme):
    FPS = {"idle": 24, "think": 24, "speak": 28, "attention": 24}
    PIP_COLOR = GREEN

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        self.seg_w = w * SEG_FRAC
        self._rng = random.Random(7)
        # taśmociąg: pozycje środków segmentów i przypisane sprite'y
        self.seg_x = [self.seg_w / 2.0 + i * self.seg_w for i in range(N_SEG)]
        self.seg_img = ["seg_idle_0"] * N_SEG
        self.speed_cur = SPEED["idle"]
        self.gate_speak = 0.0         # bramki kropki pulsu (płynny wjazd/zjazd)
        self.gate_attn = 0.0

    def _sprites(self):
        s = self.scale
        w_px, h_px = int(self.w * s), int(self.h * s)
        seg_px = int(self.seg_w * s)
        spr = {"bar": dark_bar(w_px, h_px, alpha=0.14),
               "dot": glow_dot(self.h * 0.34 * s, GREEN, boost=2.0),
               "adot": glow_dot(self.h * 0.34 * s, AMBER, boost=2.0)}
        for mode, (beats_range, amp, seed) in BEATS.items():
            color = AMBER if mode == "attention" else GREEN
            for v in range(N_VARIANTS):
                spr[f"seg_{mode}_{v}"] = segment_tile(
                    seg_px, h_px, beats_range, amp,
                    seed=seed * 101 + v, color=color)
        return spr

    def _layers(self):
        cx, cy = self.w / 2.0, self.h / 2.0
        specs = [{"img": "bar", "w": self.w, "h": self.h,
                  "x": cx, "y": cy, "op": 1.0}]
        self.i_bar = 0
        self.i_seg = []
        for _ in range(N_SEG):
            self.i_seg.append(len(specs))
            specs.append({"img": "seg_idle_0", "w": self.seg_w, "h": self.h,
                          "x": cx, "y": cy, "op": 0.9})
        self.i_dot = len(specs)
        specs.append({"img": "dot", "w": self.h * 0.34, "h": self.h * 0.34,
                      "x": self.w * 0.86, "y": cy, "op": 0.0})
        return specs

    def _enter(self, mode):
        pass            # ciągłość zapisu: tryb zmienia tylko to, co wjeżdża

    def _step(self, dt, now, level):
        mode = self.mode if self.mode in BEATS else "idle"
        target = SPEED[mode]
        if mode == "think":
            target *= age_mult(self.snap.get("age", 0.0))
        # płynna zmiana tempa papieru zamiast skoku
        self.speed_cur += (target - self.speed_cur) * (1.0 - math.exp(-dt / SPEED_TAU))

        cy = self.h / 2.0
        half = self.seg_w / 2.0
        total = N_SEG * self.seg_w
        for j in range(N_SEG):
            self.seg_x[j] -= self.speed_cur * dt
            if self.seg_x[j] < -half:            # zjechał z ekranu -> zawróć
                self.seg_x[j] += total           # na prawy koniec taśmociągu
                self.seg_img[j] = f"seg_{mode}_{self._rng.randrange(N_VARIANTS)}"
            idx = self.i_seg[j]
            self.pos(idx, self.seg_x[j], cy)
            self.img(idx, self.seg_img[j])
            self.op(idx, 0.9)

        # kropka pulsu: jasność po bramkach; sprite przełączany, gdy dominująca
        # bramka się zmienia (obie są wtedy przy zerze, więc bez skoku koloru)
        self.gate_speak = ease_step(self.gate_speak,
                                    1.0 if mode == "speak" else 0.0, dt, GATE_TAU)
        self.gate_attn = ease_step(self.gate_attn,
                                   1.0 if mode == "attention" else 0.0, dt, GATE_TAU)
        self.img(self.i_dot, "adot" if self.gate_attn > self.gate_speak else "dot")
        self.op(self.i_dot,
                self.gate_speak * (0.25 + 0.75 * level)
                + self.gate_attn * 0.9 * blink(now))
