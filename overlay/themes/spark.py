"""Motyw Spark („Kocie oko") — strumień iskier przez soczewkę-oko.

Adaptacja wizualizacji SPARK do listwy. W centrum świeci soczewka w kształcie
kociego oka (almond: ostre końce, jasna pionowa „źrenica", zielona poświata).
Przez cały czas płynie przenośnik iskier: ciemniejsze kropki suną powoli z lewej,
zbiegają do oka, a za nim przyspieszają i szybko wylatują w prawo jako jasne
zielone smugi. Model hosta jest sprite'owy (op/pos/img), więc obrót oka robimy
podmieniając pre-renderowane almondy w krokach kąta.

  idle      -> oko ledwo tli, przenośnik powolny i rzadki
  think     -> jasne oko, gęsty szybki strumień; przyspiesza z wiekiem roboty
  speak     -> oko kładzie się poziomo (90°) i pulsuje wielkością wg głośności
  attention -> całość przechodzi w bursztyn i niespokojnie mruga

Wyjście z mowy to płynny powrót: kąt i wielkość wracają easingiem do idle/think.
"""

import math
import random

from PIL import Image

from .base import Theme, age_mult, blink, ease_step, glow_dot

# --- paleta ------------------------------------------------------------------
CORE = (216, 255, 236)          # rozpalona źrenica (biel z zielonym tonem)
IRIS = (44, 226, 140)           # tęczówka, akcent #22e08a
G_GLOW = (26, 190, 118)         # poświata oka
DOT_DIM = (104, 168, 132)       # ciemniejsza kropka wlatująca z lewej
SPARK_HOT = (60, 236, 156)      # jasna smuga wylatująca w prawo
AM_CORE = (255, 240, 190)
AM_IRIS = (255, 176, 24)
AM_GLOW = (206, 128, 16)
AM_DOT = (168, 122, 54)
AM_SPARK = (255, 198, 78)

# almondy w krokach kąta 0..90° × poziomach wielkości (podmieniane co klatka)
ANGLES = (0, 15, 30, 45, 60, 75, 90)
N_ANG = len(ANGLES)
# (szerokość źrenicy w pt, wysokość oka jako ułamek listwy)
SIZE_DEFS = ((8.0, 0.50), (11.0, 0.82), (11.0, 1.22), (14.0, 1.55))
N_SIZE = len(SIZE_DEFS)

DOT_D = 5.0                     # średnica ciemnej kropki (pt)
STREAK_W = 15.0                 # długość jasnej smugi (pt)
STREAK_H = 5.0

DENSITY = {"idle": 0.5, "think": 1.0, "speak": 0.85, "attention": 0.9}
SPEED_MULT = {"idle": 0.7, "think": 1.0, "speak": 1.0, "attention": 1.0}
LENS_OP = {"idle": 0.6, "think": 0.95, "speak": 0.8, "attention": 0.95}
SIZE_TARGET = {"idle": 0.0, "think": 1.0, "attention": 1.0}   # speak liczony z głosu


def _lerp(a, b, t):
    return a + (b - a) * t


def _smoothstep(e):
    return e * e * (3.0 - 2.0 * e)


def almond_sprite(side, bw, bh, ang_deg, core_col, iris_col, glow_col,
                  core_a, glow_a, glow_hw):
    """Kocie oko: almond o półszerokości bw/2 i długości bh, obrócony o ang_deg,
    z jasną źrenicą w osi i miękką poświatą. Rysowany w kwadracie side×side px."""
    img = Image.new("RGBA", (int(side), int(side)), (0, 0, 0, 0))
    p = img.load()
    c0 = side / 2.0
    a = math.radians(-ang_deg)
    ca, sa = math.cos(a), math.sin(a)
    core_w = bw * 0.16 + 1.0
    half_bh = bh / 2.0
    for y in range(int(side)):
        dy = (y + 0.5) - c0
        for x in range(int(side)):
            dx = (x + 0.5) - c0
            lx = dx * ca - dy * sa             # współrzędne lokalne (oś oka)
            ly = dx * sa + dy * ca
            vN = ly / bh + 0.5
            if 0.0 <= vN <= 1.0:
                env = math.sin(math.pi * vN)   # 0 na czubkach -> almond
            else:
                d_end = abs(ly) - half_bh
                if d_end > bh * 0.16:
                    continue
                env = 0.5 * math.exp(-((d_end / (bh * 0.07)) ** 2))
            glow = math.exp(-((lx / glow_hw) ** 2)) * env
            body = core = 0.0
            if 0.0 <= vN <= 1.0:
                halfw = (bw / 2.0) * (math.sin(math.pi * vN) ** 1.4)
                if halfw > 0.6:
                    edge = 1.0 - min(abs(lx) / halfw, 1.0)
                    body = _smoothstep(edge)
                    core = math.exp(-((lx / core_w) ** 2))
            cw, bwv, gw = core * core_a, body * 0.7, glow * glow_a
            alpha = min(1.0, cw + bwv + gw)
            if alpha <= 0.004:
                continue
            tot = cw + bwv + gw + 1e-6
            r = (core_col[0] * cw + iris_col[0] * bwv + glow_col[0] * gw) / tot
            g = (core_col[1] * cw + iris_col[1] * bwv + glow_col[1] * gw) / tot
            bl = (core_col[2] * cw + iris_col[2] * bwv + glow_col[2] * gw) / tot
            p[x, y] = (int(r), int(g), int(bl),
                       max(0, min(255, int(255 * alpha))))
    return img


def _dot_in_canvas(w_px, h_px, diam, color):
    """Mała, ciemniejsza świecąca kropka wyśrodkowana w płótnie rozmiaru smugi
    (ta sama wielkość warstwy co smuga -> podmiana bez zniekształceń)."""
    img = Image.new("RGBA", (int(w_px), int(h_px)), (0, 0, 0, 0))
    dot = glow_dot(diam, color, boost=1.0)
    img.alpha_composite(dot, (int((w_px - dot.width) / 2),
                              int((h_px - dot.height) / 2)))
    return img


def streak_sprite(w_px, h_px, color, head_col):
    """Jasna smuga: gorąca głowa po prawej, gasnący ogon w lewo."""
    img = Image.new("RGBA", (int(w_px), int(h_px)), (0, 0, 0, 0))
    p = img.load()
    cy = h_px / 2.0
    for x in range(int(w_px)):
        xf = (x + 0.5) / w_px
        head = xf ** 2.2
        whiten = xf ** 3.0
        r = _lerp(color[0], head_col[0], whiten)
        g = _lerp(color[1], head_col[1], whiten)
        b = _lerp(color[2], head_col[2], whiten)
        for y in range(int(h_px)):
            prof = math.exp(-(((y + 0.5) - cy) / (h_px * 0.33)) ** 2)
            alpha = head * prof
            if alpha <= 0.004:
                continue
            p[x, y] = (int(r), int(g), int(b),
                       max(0, min(255, int(255 * alpha))))
    return img


class SparkTheme(Theme):
    FPS = {"idle": 18, "think": 26, "speak": 30, "attention": 22}
    PIP_COLOR = IRIS

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        self.cx = w / 2.0
        self.mid = h / 2.0
        self.side = 3.0 * h                       # bok sprite'a oka (pt, z zapasem na poświatę)
        # przenośnik: powolna lewa strona, ~8× szybsza prawa
        self.v_slow = self.cx / 3.6
        self.v_fast = (w - self.cx) / 0.5
        self.n = max(16, min(40, int(w / 40.0)))
        rng = random.Random(11)
        self.par = [{"x": rng.uniform(0.0, w), "y0": rng.uniform(0.0, h),
                     "drift": rng.uniform(-0.32, 0.32) * h,
                     "vs": rng.uniform(0.8, 1.35), "tw": rng.uniform(0, math.tau)}
                    for _ in range(self.n)]
        # wygładzane stany (cele trybu; wartość zawsze płynie)
        self.rot = 0.0
        self.size_lvl = SIZE_TARGET["idle"]
        self.dens = DENSITY["idle"]
        self.cur_mult = SPEED_MULT["idle"]
        self.lens_op = LENS_OP["idle"]
        self.attn_gate = 0.0

    def _sprites(self):
        s = self.scale
        side = self.side * s
        spr = {}
        glow_hw = 0.85 * (12.0 * s) + 0.05 * self.h * s    # rozmycie w poprzek osi
        for si, (bw_pt, bh_frac) in enumerate(SIZE_DEFS):
            bw, bh = bw_pt * s, bh_frac * self.h * s
            ca = 0.85 + 0.1 * (bh_frac / SIZE_DEFS[-1][1])
            for ai, ang in enumerate(ANGLES):
                spr[f"g{ai}_{si}"] = almond_sprite(
                    side, bw, bh, ang, CORE, IRIS, G_GLOW, ca, 0.5, glow_hw)
            spr[f"a{si}"] = almond_sprite(
                side, bw, bh, 0, AM_CORE, AM_IRIS, AM_GLOW, ca, 0.5, glow_hw)
        spr["dot"] = _dot_in_canvas(STREAK_W * s, STREAK_H * s, DOT_D * s, DOT_DIM)
        spr["adot"] = _dot_in_canvas(STREAK_W * s, STREAK_H * s, DOT_D * s, AM_DOT)
        spr["streak"] = streak_sprite(STREAK_W * s, STREAK_H * s, SPARK_HOT, CORE)
        spr["astreak"] = streak_sprite(STREAK_W * s, STREAK_H * s, AM_SPARK, AM_CORE)
        return spr

    def _layers(self):
        lens = {"w": self.side, "h": self.side, "x": self.cx, "y": self.mid}
        specs = [dict(lens, img="g0_0", op=LENS_OP["idle"]),   # 0 zielone oko
                 dict(lens, img="a0", op=0.0)]                 # 1 bursztynowe
        self.i_lens_g, self.i_lens_a = 0, 1
        self.i_par0 = len(specs)
        for _ in range(self.n):
            specs.append({"img": "dot", "w": STREAK_W, "h": STREAK_H,
                          "x": 0.0, "y": self.mid, "op": 0.0})
        return specs

    def _enter(self, mode):
        pass                                       # przenośnik płynie ciągle

    def _step(self, dt, now, level):
        mode = self.mode if self.mode in DENSITY else "idle"
        amber = mode == "attention"

        mult_t = SPEED_MULT[mode]
        if mode == "think":
            mult_t *= age_mult(self.snap.get("age", 0.0))
        if mode == "speak":
            size_t = max(1.2, min(3.0, 1.4 + 1.7 * level))
            op_t = min(1.0, 0.68 + 0.32 * level)
            rot_t = math.pi / 2.0
        else:
            size_t = SIZE_TARGET[mode]
            op_t = LENS_OP[mode]
            rot_t = 0.0
            if amber:
                op_t *= 0.6 + 0.4 * blink(now, period=1.2,
                                          pulses=((0.0, 0.30), (0.5, 0.80)))

        self.cur_mult = ease_step(self.cur_mult, mult_t, dt, 0.5)
        self.dens = ease_step(self.dens, DENSITY[mode], dt, 0.5)
        self.rot = ease_step(self.rot, rot_t, dt, 0.5)
        self.size_lvl = ease_step(self.size_lvl, size_t, dt,
                                  0.12 if mode == "speak" else 0.4)
        self.lens_op = ease_step(self.lens_op, op_t, dt, 0.4)
        self.attn_gate = ease_step(self.attn_gate, 1.0 if amber else 0.0, dt, 0.6)

        self._draw_lens(now, mode)
        self._draw_stream(dt, now)

    # --- oko ---------------------------------------------------------------
    def _draw_lens(self, now, mode):
        ai = int(round(self.rot / (math.pi / 2.0) * (N_ANG - 1)))
        ai = max(0, min(N_ANG - 1, ai))
        si = int(round(max(0.0, min(float(N_SIZE - 1), self.size_lvl))))
        flick = 1.0
        if mode in ("think", "attention"):
            flick = 0.86 + 0.14 * random.random()
        jx = jy = 0.0
        if mode == "think":
            jx = (math.sin(now * 47.3) + math.sin(now * 71.7 + 1.3)) * 0.8
            jy = (math.sin(now * 53.1 + 0.7)) * 0.6
        self.img(self.i_lens_g, f"g{ai}_{si}")
        self.img(self.i_lens_a, f"a{si}")
        self.pos(self.i_lens_g, self.cx + jx, self.mid + jy)
        self.pos(self.i_lens_a, self.cx + jx, self.mid + jy)
        op = self.lens_op * flick
        self.op(self.i_lens_g, op * (1.0 - self.attn_gate))
        self.op(self.i_lens_a, op * self.attn_gate)

    # --- przenośnik iskier (powoli z lewej -> szybko w prawo) --------------
    def _draw_stream(self, dt, now):
        amber = self.attn_gate > 0.5
        dot_key = "adot" if amber else "dot"
        streak_key = "astreak" if amber else "streak"
        w, cx, mid = self.w, self.cx, self.mid
        fade_edge = w * 0.05
        for i, p in enumerate(self.par):
            left = p["x"] < cx
            v = (self.v_slow if left else self.v_fast) * self.cur_mult * p["vs"]
            p["x"] += v * dt
            if p["x"] >= w:
                p["x"] -= w
                p["y0"] = random.uniform(0.0, self.h)
                p["drift"] = random.uniform(-0.32, 0.32) * self.h
                p["vs"] = random.uniform(0.8, 1.35)
                p["tw"] = random.uniform(0, math.tau)
                left = True
            idx = self.i_par0 + i
            x = p["x"]
            gate = max(0.0, min(1.0, self.dens * self.n - i))
            fade = min(1.0, x / fade_edge, (w - x) / fade_edge)
            twinkle = 0.85 + 0.15 * math.sin(now * 5.0 + p["tw"])
            bright = 0.5 if left else 1.0
            op = bright * fade * twinkle * gate
            if op <= 0.004:
                self.op(idx, 0.0)
                continue
            if left:                               # zbiega ku osi oka
                conv = (x / cx) * 0.6
                y = _lerp(p["y0"], mid, conv)
            else:                                  # rozbiega się w prawo
                yc = _lerp(p["y0"], mid, 0.6)
                y = yc + p["drift"] * ((x - cx) / (w - cx))
            self.img(idx, dot_key if left else streak_key)
            self.pos(idx, x, y)
            self.op(idx, op)
