"""Motyw Spark („Kocie oko") — strumień iskier przez soczewkę-oko.

Adaptacja wizualizacji SPARK do listwy. W centrum świeci soczewka w kształcie
kociego oka (almond: ostre końce, jasna pionowa „źrenica", zielona poświata).
Przez cały czas płynie przenośnik iskier: ciemniejsze kropki suną powoli z lewej,
zbiegają do oka, a za nim przyspieszają i szybko wylatują w prawo jako jasne
zielone smugi. Oko obraca się płynnie transformacją warstwy (op/pos/img/rot),
więc trzymamy jeden pionowy almond na każdy poziom wielkości.

  idle      -> małe, przygaszone, spokojne oko; strumień powolny i rzadki
  think     -> większe jasne oko z wyraźnym drżeniem; gęsty szybki strumień
  speak     -> oko kładzie się poziomo (90°) i pulsuje wg głosu; BEZ iskier
  (uwaga)   -> ktoś czeka na usera: RUCH bez zmian, tylko oko i iskry zmieniają
               kolor (niebieski / cyjan przy mowie) aż do reakcji

Soczewka jest ZAWSZE zielona. Liczbę pracujących agentów pokazuje LICZBA
soczewek: przy 2 agentach oko rozdziela się płynnie na dwie soczewki, przy 3 na
trzy (maks. 5); gdy agent kończy, soczewki się scalają. Przed obrotem i mową
soczewki najpierw scalają się w jedną, dopiero potem oko się obraca (i odwrotnie
przy wyjściu z mowy). Wyjście z mowy to płynny powrót easingiem do idle/think.
"""

import math
import random

from PIL import Image

from .base import Theme, age_mult, ease_step, glow_dot

# --- paleta ------------------------------------------------------------------
CORE = (216, 255, 236)          # rozpalona źrenica (biel z zielonym tonem)
IRIS = (44, 226, 140)           # tęczówka, akcent #22e08a
G_GLOW = (26, 190, 118)         # poświata oka
DOT_DIM = (104, 168, 132)       # ciemniejsza kropka wlatująca z lewej
STREAK_HEAD = (242, 248, 252)   # rozgrzana głowa smugi (biała -> stygnie w kolor)
# uwaga (ktoś czeka na usera) = tylko KOLOR; iskry i oko na niebiesko, a przy
# mowie oko na cyjan. Ruch bez zmian.
ATT_DOT = (70, 122, 194)        # niebieskie iskry gdy ktoś czeka
ATT_SPARK = (96, 174, 255)
ATT_HEAD = (214, 232, 255)      # jasnoniebieska głowa smugi
EYE_ATT = (74, 150, 255)        # niebieskie oko gdy czeka (idle/think)
EYE_ATT_GLOW = (40, 110, 220)
EYE_ATT_SPEAK = (54, 214, 255)  # cyjanowe oko gdy mówi, a ktoś czeka
EYE_ATT_SPEAK_GLOW = (26, 160, 220)

# kolor stygnącego ogona wylatującej iskry wg liczby agentów (1..5)
COUNT_COLORS = ((54, 232, 150),    # 1 zielony (tożsamość motywu)
                (255, 150, 44),    # 2 pomarańczowy
                (255, 66, 52),     # 3 czerwony
                (70, 150, 255),    # 4 niebieski
                (176, 96, 255))    # 5 fioletowy

# jeden bazowy pionowy almond, skalowany PŁYNNIE transformacją (bez skoków).
LENS_BW = 15.0                  # bazowa szerokość źrenicy (pt) przy skali 1
LENS_BH = 1.05                  # bazowa długość oka (ułamek listwy) przy skali 1
# docelowe skale (sx=szerokość, sy=długość) per tryb; speak liczony z głosu
SCALE_XY = {"idle": (0.5, 0.5), "think": (0.82, 0.9)}

DOT_D = 5.0                     # średnica ciemnej kropki (pt)
STREAK_W = 15.0                 # długość jasnej smugi (pt)
STREAK_H = 5.0

MAXL = 5                        # maks. liczba rozdzielonych soczewek (1 na agenta)
LENS_SEP = 30.0                 # rozstaw soczewek przy pełnym rozdzieleniu (pt)

# reaktywne drżenie: każda iskra WPADAJĄCA do soczewki dolewa do licznika
# animacji; oko trzęsie się póki licznik > 0, potem płynnie wraca do zera.
SHAKE_PER_SPARK = 0.07          # sekundy dodane na jedną iskrę (do strojenia)
SHAKE_MAX = 0.5                 # górny limit licznika (nie trzęsie się bez końca)

# iskry lecą tylko gdy pracuje/czeka agent (think/attention); w idle i przy
# mowie strumień gaśnie. Gęstość rośnie z liczbą agentów (patrz _step).
SPEED_MULT = {"idle": 0.55, "think": 1.0, "speak": 1.0}
LENS_OP = {"idle": 0.55, "think": 0.95, "speak": 0.8}


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
        self.n = max(20, min(56, int(w / 30.0)))   # pula iskier (skalowana busy)
        rng = random.Random(11)
        self.par = [{"x": rng.uniform(0.0, w), "y0": rng.uniform(0.0, h),
                     "drift": rng.uniform(-0.32, 0.32) * h,
                     "vs": rng.uniform(0.8, 1.35), "tw": rng.uniform(0, math.tau),
                     "c": 1}                        # kolor ogona (1..5, wg agentów)
                    for _ in range(self.n)]
        self.nbusy = 1                              # liczba agentów (kolor + prędkość)
        # wygładzane stany (cele trybu; wartość zawsze płynie)
        self.rphase = 0.0                          # faza obrotu 0..1 (0=pion, 1=poziom)
        self.lens_x = [self.cx] * MAXL             # pozycje X soczewek (rozjazd)
        self.lens_a = [1.0 if i == 0 else 0.0 for i in range(MAXL)]  # aktywacja
        self.sx, self.sy = SCALE_XY["idle"]        # płynna skala oka (bez skoków)
        self.dens = 0.0                            # gęstość iskier (0 w idle)
        # drżenie PER SOCZEWKA — każde oko ma własny licznik i fazę wobble,
        # więc dwa oczy nie trzęsą się identycznie (osobno, gdy iskra w nie trafi)
        self.shake_t = [0.0] * MAXL                # licznik animacji drżenia (s)
        self.shake_amp = [0.0] * MAXL              # obwiednia drżenia 0..1
        self.lens_ph = [rng.uniform(0, math.tau) for _ in range(MAXL)]  # faza wobble
        self.cur_mult = SPEED_MULT["idle"]
        self.lens_op = LENS_OP["idle"]
        self.attn_gate = 0.0

    def _sprites(self):
        s = self.scale
        side = self.side * s
        spr = {}
        glow_hw = 0.85 * (12.0 * s) + 0.05 * self.h * s    # rozmycie w poprzek osi
        # jeden bazowy almond (host skaluje/obraca go płynnie transformacją)
        bw, bh = LENS_BW * s, LENS_BH * self.h * s
        spr["g"] = almond_sprite(side, bw, bh, 0, CORE, IRIS, G_GLOW, 0.93, 0.5, glow_hw)
        # oko przemalowane, gdy ktoś czeka (idle/think = niebieskie, mowa = cyjan)
        spr["g_attn"] = almond_sprite(side, bw, bh, 0, CORE, EYE_ATT, EYE_ATT_GLOW,
                                      0.93, 0.5, glow_hw)
        spr["g_attn_speak"] = almond_sprite(side, bw, bh, 0, CORE, EYE_ATT_SPEAK,
                                            EYE_ATT_SPEAK_GLOW, 0.93, 0.5, glow_hw)
        spr["dot"] = _dot_in_canvas(STREAK_W * s, STREAK_H * s, DOT_D * s, DOT_DIM)
        spr["adot"] = _dot_in_canvas(STREAK_W * s, STREAK_H * s, DOT_D * s, ATT_DOT)
        # smugi wylotowe: kolor ogona wg liczby agentów (głowa zawsze biała)
        for c, col in enumerate(COUNT_COLORS, start=1):
            spr[f"streak{c}"] = streak_sprite(STREAK_W * s, STREAK_H * s, col,
                                              STREAK_HEAD)
        spr["astreak"] = streak_sprite(STREAK_W * s, STREAK_H * s, ATT_SPARK,
                                        ATT_HEAD)                # niebieski w uwadze
        return spr

    def _layers(self):
        lens = {"w": self.side, "h": self.side, "x": self.cx, "y": self.mid}
        specs = [dict(lens, img="g", op=(LENS_OP["idle"] if i == 0 else 0.0))
                 for i in range(MAXL)]             # pula soczewek (1 na agenta)
        self.i_lens_g = 0                          # pierwsza soczewka (zawsze aktywna)
        self.i_alens0 = len(specs)                 # nakładka koloru uwagi (na oko)
        specs += [dict(lens, img="g_attn", op=0.0) for _ in range(MAXL)]
        self.i_par0 = len(specs)
        for _ in range(self.n):
            specs.append({"img": "dot", "w": STREAK_W, "h": STREAK_H,
                          "x": 0.0, "y": self.mid, "op": 0.0})
        return specs

    def _enter(self, mode):
        pass                                       # przenośnik płynie ciągle

    def _step_pips(self, dt):
        pass                                       # licznik sesji pokazują soczewki

    def _step(self, dt, now, level):
        mode = self.mode if self.mode in SPEED_MULT else "idle"
        waiting = bool(self.snap.get("waiting"))   # ktoś czeka na usera -> KOLOR
        nbusy = max(1, min(MAXL, int(self.snap.get("busy", 1))))
        self.nbusy = nbusy

        mult_t = SPEED_MULT[mode]
        if mode == "think":
            mult_t *= age_mult(self.snap.get("age", 0.0))
        mult_t *= 1.0 + 0.2 * (nbusy - 1)          # więcej agentów -> szybszy strumień
        if mode == "speak":
            # oko rośnie/kurczy się PŁYNNIE z głosem — CZUŁE: krzywa ^0.6 podbija
            # ciche dźwięki, większy zakres, więc oko wyraźnie się rusza
            resp = level ** 0.6
            sx_t = 0.80 + 0.55 * resp
            sy_t = 0.80 + 1.5 * resp
            op_t = min(1.0, 0.64 + 0.36 * resp)
        else:
            sx_t, sy_t = SCALE_XY[mode]
            op_t = LENS_OP[mode]

        # iskry: brak w idle i przy mowie; w think gęstość rośnie
        # z liczbą agentów (więcej soczewek -> gęstszy strumień)
        if mode in ("idle", "speak"):
            dens_t = 0.0
        else:
            dens_t = min(1.0, 0.16 + 0.17 * nbusy)

        self.cur_mult = ease_step(self.cur_mult, mult_t, dt, 0.5)
        self.dens = ease_step(self.dens, dens_t, dt, 0.5)
        stau = 0.06 if mode == "speak" else 0.4    # mowa: szybka, czuła reakcja
        self.sx = ease_step(self.sx, sx_t, dt, stau)
        self.sy = ease_step(self.sy, sy_t, dt, stau)
        self.lens_op = ease_step(self.lens_op, op_t, dt, 0.4)
        self.attn_gate = ease_step(self.attn_gate, 1.0 if waiting else 0.0, dt, 0.5)

        # --- rozdzielenie soczewek (1 na agenta) + sekwencja scal↔obróć ----
        speak = mode == "speak"
        # przy mowie lub póki jeszcze obrócone: trzymaj scalone w jedną
        eff = 1 if (speak or self.rphase > 0.08) else nbusy
        spread = max(abs(self.lens_x[i] - self.cx) for i in range(MAXL))
        extra = max(self.lens_a[i] for i in range(1, MAXL))
        merged = spread < 0.6 and extra < 0.06
        # obracaj dopiero PO scaleniu; scalaj/odobracaj zawsze swobodnie
        rot_goal = 1.0 if speak else 0.0
        if rot_goal > self.rphase and not merged:
            rot_goal = self.rphase
        self.rphase = ease_step(self.rphase, rot_goal, dt, 0.45)

        # drżenie reaktywne PER SOCZEWKA: każde oko odlicza własny licznik i
        # ma własną obwiednię (wjeżdża szybko, wraca płynnie)
        for i in range(MAXL):
            self.shake_t[i] = max(0.0, self.shake_t[i] - dt)
            a_t = 1.0 if self.shake_t[i] > 1e-4 else 0.0
            self.shake_amp[i] = ease_step(self.shake_amp[i], a_t, dt,
                                          0.03 if a_t > self.shake_amp[i] else 0.09)

        for i in range(MAXL):
            active = i < eff
            tx = self.cx + (i - (eff - 1) / 2.0) * LENS_SEP if active else self.cx
            self.lens_x[i] = ease_step(self.lens_x[i], tx, dt, 0.35)
            self.lens_a[i] = ease_step(self.lens_a[i], 1.0 if active else 0.0,
                                       dt, 0.3)

        self._draw_lens(now, mode)
        self._draw_stream(dt, now)

    # --- oko (zawsze zielone, obracane płynnie, dzielone wg liczby agentów) -
    def _draw_lens(self, now, mode):
        g = self.attn_gate                          # 0 = zielone, 1 = kolor uwagi
        attn_key = "g_attn_speak" if mode == "speak" else "g_attn"
        base_ang = self.rphase * (math.pi / 2.0)
        for i in range(MAXL):
            # drżenie + przechył OSOBNO per oko: własna obwiednia + faza wobble,
            # więc dwa oczy nie trzęsą się identycznie
            a = self.shake_amp[i]
            ph = self.lens_ph[i]
            flick = 1.0 - 0.18 * a * random.random()
            jx = (math.sin(now * 21.0 + ph) + math.sin(now * 33.0 + 1.3 + ph)) * 1.9 * a
            jy = (math.sin(now * 27.0 + 0.7 + ph) + math.sin(now * 39.0 + 2.1 + ph)) * 1.1 * a
            jr = math.sin(now * 24.0 + 0.4 + ph) * 0.11 * a   # lekki przechył (~6°)
            ang = base_ang + jr
            x = self.lens_x[i] + jx
            op = self.lens_op * flick * self.lens_a[i]
            ai = self.i_alens0 + i
            # zielone oko (gaśnie przy uwadze) + kolorowa nakładka (wchodzi) —
            # obie identycznie transformowane, więc kolor przechodzi płynnie
            for idx, key, frac in ((i, "g", 1.0 - g), (ai, attn_key, g)):
                o = op * frac
                if o <= 0.004:
                    self.op(idx, 0.0)
                    continue
                self.img(idx, key)
                self.xf(idx, ang, self.sx, self.sy)
                self.pos(idx, x, self.mid + jy)
                self.op(idx, o)

    # --- przenośnik iskier (powoli z lewej -> szybko w prawo) --------------
    def _draw_stream(self, dt, now):
        amber = self.attn_gate > 0.5
        dot_key = "adot" if amber else "dot"
        w, cx, mid = self.w, self.cx, self.mid
        fade_edge = w * 0.05
        for i, p in enumerate(self.par):
            prev_x = p["x"]
            was_left = prev_x < cx
            v = (self.v_slow if was_left else self.v_fast) * self.cur_mult * p["vs"]
            p["x"] += v * dt
            nx = p["x"]
            gate = max(0.0, min(1.0, self.dens * self.n - i))
            # iskra przelatuje przez soczewki PO KOLEI: uderza w każdą, której X
            # właśnie mija (najpierw lewą, potem kolejne) -> jej licznik drżenia
            if gate > 0.5:
                for li in range(MAXL):
                    if self.lens_a[li] > 0.5 and prev_x < self.lens_x[li] <= nx:
                        self.shake_t[li] = min(SHAKE_MAX,
                                               self.shake_t[li] + SHAKE_PER_SPARK)
            if p["x"] >= w:
                p["x"] -= w
                p["y0"] = random.uniform(0.0, self.h)
                p["drift"] = random.uniform(-0.32, 0.32) * self.h
                p["vs"] = random.uniform(0.8, 1.35)
                p["tw"] = random.uniform(0, math.tau)
                p["c"] = self.nbusy                # kolor ogona wg agentów przy starcie
            left = p["x"] < cx
            idx = self.i_par0 + i
            x = p["x"]
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
            if left:
                key = dot_key
            else:                                  # ogon w kolorze wg agentów
                key = "astreak" if amber else f"streak{p['c']}"
            self.img(idx, key)
            self.pos(idx, x, y)
            self.op(idx, op)
