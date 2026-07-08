"""Motyw HAL 9000 — czerwone oko na środku listwy.

  idle      -> ledwo tli się, bardzo wolne oddychanie
  think     -> wyraźniejsze, szybsze oddychanie (przyspiesza z wiekiem roboty)
  speak     -> jasność rdzenia podąża za obwiednią głosu
  attention -> bursztynowy pierścień mruga podwójnym błyskiem wokół oka
"""

import math

from .base import (
    AMBER,
    GATE_TAU,
    Theme,
    age_mult,
    blink,
    ease_step,
    glow_dot,
)

RED_GLOW = (200, 28, 18)
RED_IRIS = (255, 42, 24)
CORE_HL = (255, 214, 130)


class HalTheme(Theme):
    FPS = {"idle": 15, "think": 21, "speak": 28, "attention": 21}
    PIP_COLOR = RED_IRIS

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        self.ph = 0.0
        # wartości NA ekranie — cele per tryb dochodzą do nich easingiem
        self.cur = {"glow": 0.3, "iris": 0.4, "core": 0.25}
        self.ring_gate = 0.0

    # oko powiekszone ~1.6x wzgledem pierwotnego (maksimum mieszczace sie w
    # listwie bez ciecia w "bande"); bez podkladu (housing) — samo swiecace oko
    def _sprites(self):
        s, h = self.scale, self.h
        return {
            "glow": glow_dot(h * 1.25 * s, RED_GLOW, boost=1.3),
            "iris": glow_dot(h * 0.99 * s, RED_IRIS, boost=1.9),
            "core": glow_dot(h * 0.35 * s, CORE_HL, boost=2.2),
            "ring": glow_dot(h * 1.47 * s, AMBER, boost=1.5),
        }

    def _layers(self):
        cx, cy, h = self.w / 2.0, self.h / 2.0, self.h
        self.i_glow, self.i_iris, self.i_core, self.i_ring = range(4)
        return [
            {"img": "glow", "w": h * 1.25, "h": h * 1.25, "x": cx, "y": cy, "op": 0.3},
            {"img": "iris", "w": h * 0.99, "h": h * 0.99, "x": cx, "y": cy, "op": 0.4},
            {"img": "core", "w": h * 0.35, "h": h * 0.35, "x": cx, "y": cy, "op": 0.25},
            {"img": "ring", "w": h * 1.47, "h": h * 1.47, "x": cx, "y": cy, "op": 0.0},
        ]

    def _enter(self, mode):
        pass                                     # ciągła faza — bez skoków

    def _step(self, dt, now, level):
        mode = self.mode
        if mode == "think":
            period = 2.0 / age_mult(self.snap.get("age", 0.0))
        elif mode == "idle":
            period = 6.0
        else:
            period = 3.0
        self.ph += dt * 2.0 * math.pi / period
        breath = 0.5 + 0.5 * math.sin(self.ph)

        if mode == "speak":
            glow = 0.55 + 0.35 * level
            iris = 0.45 + 0.55 * level
            core = 0.25 + 0.75 * level
        elif mode == "think":
            glow = 0.50 + 0.30 * breath
            iris = 0.55 + 0.35 * breath
            core = 0.35 + 0.30 * breath
        elif mode == "attention":
            glow, iris, core = 0.35, 0.40 + 0.10 * breath, 0.30
        else:                                     # idle
            glow = 0.22 + 0.12 * breath
            iris = 0.30 + 0.10 * breath
            core = 0.20 + 0.06 * breath

        # cele per tryb, na ekran zawsze easingiem (zmiana trybu nie skacze);
        # błysk pierścienia zostaje ostry, ale wjeżdża/zjeżdża po bramce
        cur = self.cur
        for key, target in (("glow", glow), ("iris", iris), ("core", core)):
            cur[key] = ease_step(cur[key], target, dt, 0.35)
        self.ring_gate = ease_step(self.ring_gate,
                                   1.0 if mode == "attention" else 0.0,
                                   dt, GATE_TAU)

        self.op(self.i_glow, cur["glow"])
        self.op(self.i_iris, cur["iris"])
        self.op(self.i_core, cur["core"])
        self.op(self.i_ring, 0.9 * blink(now) * self.ring_gate)
