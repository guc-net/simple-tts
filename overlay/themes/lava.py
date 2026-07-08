"""Motyw Lava — płynna plazma na całą listwę.

Zapętlona sekwencja klatek plazmy (renderowana raz, w niskiej rozdzielczości
i skalowana bilinearnie — plazma jest gładka, więc nie widać różnicy). Host
tylko podmienia contents warstwy; tryb steruje tempem cyklu i kryciem:

  idle      -> ledwo widoczna, leniwa
  think     -> jaśniejsza i żywsza; przyspiesza z wiekiem roboty
  speak     -> krycie pulsuje w rytm głosu
  attention -> bursztynowa paleta + niespokojne pulsowanie
"""

import math

from PIL import Image

from .base import GATE_TAU, Theme, age_mult, ease_step

N_FRAMES = 16
DOWNSCALE = 4                 # render 1/4 rozdzielczości, upscale bilinearny
FPS_CYCLE = {"idle": 4.0, "think": 9.0, "speak": 11.0, "attention": 10.0}
BASE_OP = {"idle": 0.30, "think": 0.75, "speak": 0.55, "attention": 0.9}

# paleta lawy: głęboka czerwień -> pomarańcz -> rozgrzana żółć
LAVA_STOPS = ((36, 0, 0), (168, 22, 0), (255, 120, 8), (255, 226, 120))
# paleta attention: ciemny bursztyn -> jaskrawy bursztyn
AMBER_STOPS = ((44, 20, 0), (170, 90, 0), (255, 176, 24), (255, 236, 160))


def _palette(u, stops):
    """Kolor z gradientu stops dla u w 0..1."""
    u = 0.0 if u < 0.0 else 1.0 if u > 1.0 else u
    seg = u * (len(stops) - 1)
    i = min(int(seg), len(stops) - 2)
    t = seg - i
    a, b = stops[i], stops[i + 1]
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def plasma_frame(w_px, h_px, k, n_frames, stops):
    """Jedna klatka plazmy (RGBA). Fazy to całkowite wielokrotności 2π·k/n,
    więc sekwencja zapętla się idealnie po n klatkach."""
    t = 2.0 * math.pi * k / n_frames
    w0, h0 = max(8, w_px // DOWNSCALE), max(6, h_px // DOWNSCALE)
    img = Image.new("RGBA", (w0, h0))
    p = img.load()
    for y in range(h0):
        ny = y / h0
        for x in range(w0):
            nx = x / w0
            v = (math.sin(2 * math.pi * (nx * 3.0) + t)
                 + math.sin(2 * math.pi * (ny * 2.0) - t)
                 + math.sin(2 * math.pi * (nx * 2.0 + ny * 1.5) + 2 * t)
                 + math.sin(2 * math.pi * (nx * 1.0 - ny * 2.5) - 2 * t))
            u = (v + 4.0) / 8.0
            r, g, b = _palette(u ** 1.25, stops)
            a = int(255 * (0.25 + 0.75 * u))
            p[x, y] = (r, g, b, a)
    return img.resize((w_px, h_px), Image.BILINEAR)


class LavaTheme(Theme):
    FPS = {"idle": 10, "think": 14, "speak": 21, "attention": 14}
    PIP_COLOR = (255, 140, 20)

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        self.fph = 0.0
        self.pulse_ph = 0.0
        self.cur_op = BASE_OP["idle"]
        self.attn_gate = 0.0          # krosfejd czerwona <-> bursztynowa plazma

    def _sprites(self):
        w_px, h_px = int(self.w * self.scale), int(self.h * self.scale)
        spr = {}
        for k in range(N_FRAMES):
            spr[f"lava{k}"] = plasma_frame(w_px, h_px, k, N_FRAMES, LAVA_STOPS)
            spr[f"alava{k}"] = plasma_frame(w_px, h_px, k, N_FRAMES, AMBER_STOPS)
        return spr

    def _layers(self):
        # dwie warstwy plazmy (czerwona + bursztynowa) — zmiana palety to
        # krosfejd kryć, nigdy podmiana obrazu w jednej klatce
        self.i_plasma_red, self.i_plasma_amber = 0, 1
        common = {"w": self.w, "h": self.h,
                  "x": self.w / 2.0, "y": self.h / 2.0}
        return [dict(common, img="lava0", op=BASE_OP["idle"]),
                dict(common, img="alava0", op=0.0)]

    def _enter(self, mode):
        pass                                     # cykl płynie ciągle

    def _step(self, dt, now, level):
        mode = self.mode if self.mode in BASE_OP else "idle"
        cyc = FPS_CYCLE[mode]
        if mode == "think":
            cyc *= age_mult(self.snap.get("age", 0.0))
        self.fph = (self.fph + cyc * dt) % N_FRAMES
        k = int(self.fph)
        self.img(self.i_plasma_red, f"lava{k}")
        self.img(self.i_plasma_amber, f"alava{k}")

        op_t = BASE_OP[mode]
        if mode == "speak":
            op_t = 0.35 + 0.6 * level
        elif mode == "attention":
            self.pulse_ph += dt * 2.0 * math.pi * 1.6
            op_t *= 0.65 + 0.35 * (0.5 + 0.5 * math.sin(self.pulse_ph))
        self.cur_op = ease_step(self.cur_op, op_t, dt, 0.4)
        self.attn_gate = ease_step(self.attn_gate,
                                   1.0 if mode == "attention" else 0.0,
                                   dt, GATE_TAU * 2)
        self.op(self.i_plasma_red, self.cur_op * (1.0 - self.attn_gate))
        self.op(self.i_plasma_amber, self.cur_op * self.attn_gate)
