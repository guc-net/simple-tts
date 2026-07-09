"""Motyw KITT — port ciągłej symulacji diod z kitt_overlay.py.

Głowa ma płynnie animowaną pozycję (amplituda/prędkość dochodzą do celu
z wygładzeniem), ogon powstaje z wygasania diod w miejscu (afterglow),
mowa to symetryczny rozbłysk wokół środka w rytm obwiedni głosu.

Nowości względem oryginału:
  * attention -> pas gaśnie, a wszystkie cele mrugają bursztynowym podwójnym
    błyskiem (osobna warstwa amber per dioda),
  * think przyspiesza z wiekiem najstarszej roboty (age_mult).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kitt_frame as KF  # noqa: E402

from .base import GATE_TAU, Theme, age_mult, ease_step, glow_dot  # noqa: E402


def _tri(phase):
    ph = phase % 1.0
    return 1.0 - 4.0 * abs(ph - 0.5)          # -1 .. +1 .. -1


class KittTheme(Theme):
    FPS = {"idle": 21, "think": 21, "speak": 28, "attention": 21}
    PIP_COLOR = KF.CORE

    N_LED = 24                    # sporo pionowych segmentów-lamp (jak w KITT)
    LAMP = True                   # świecące segmenty = pionowe prostokąty (nie kropki)
    BACKING = False               # bez tła/oczodołów — tylko sunące światło
    EDGE = 16.0
    FLOOR = 0.0                   # zgaszona lampa niewidoczna (brak tła)
    HEAD_SIGMA = 0.05
    CORE_THRESH = 0.55
    BAR_ALPHA = 0.12
    CELL_ALPHA = 0.18
    SWEEP_HALF = 0.44
    SPEED_IDLE = 0.18
    SPEED_THINK = 0.52
    EASE_TAU = 0.22
    TAIL_TAU = 0.10
    TAIL_TAU_THINK = 0.17
    SPEAK_TAU = 0.09
    SPEAK_BASE = 0.03
    SPEAK_GAIN = 0.34
    SPEAK_EDGE = 0.06
    GLOW_COLOR = KF.CORE
    HOT_COLOR = KF.HOT
    # Uwaga (ktoś czeka na usera) NIE zmienia ruchu — tylko kolor oka, aż do
    # reakcji. Dwa kolory: gdy pracuje/idle (ATTN_COLOR) vs gdy mówi (ATTN_SPEAK).
    ATTN_COLOR = (255, 150, 20)   # KITT: pomarańcz gdy czeka
    ATTN_SPEAK = ATTN_COLOR       # KITT: TEN SAM pomarańcz też przy mowie (bez żółtego)
    MAXH = 5                      # maks. „głów" w przejeździe (1 na agenta)
    HEAD_GAP = 0.11               # odstęp głów (w 0..1) — zbita grupa

    def __init__(self, w, h, scale):
        super().__init__(w, h, scale)
        n = self.N_LED
        self._pos01 = [i / (n - 1) for i in range(n)]
        self._spacing = (w - 2 * self.EDGE) / (n - 1)
        self._xs = [self.EDGE + p * (w - 2 * self.EDGE) for p in self._pos01]
        self.cell_w = self._spacing * 0.90
        self.cell_h = h * 0.72
        self.glow_d = self._spacing * 0.86
        if self.LAMP:                              # pionowy segment-lampa
            self.glow_w = self._spacing * 0.66
            self.glow_h = h * 0.86
            self.cell_w = self._spacing * 0.50     # rdzeń węższy niż lampa
            self.cell_h = h * 0.72
        else:                                      # okrągła plama (Cylon)
            self.glow_w = self.glow_h = self.glow_d
        self.led = [0.0] * n
        self.core = [0.0] * n         # wygładzone krycie rdzenia (bez przeskoku progu)
        self.amp = self.amp_t = 0.0
        self.speed = self.speed_t = self.SPEED_IDLE
        self.bloom = self.bloom_t = 0.0
        self.phase = 0.0
        self.attn_gate = 0.0          # bramka koloru uwagi (wjeżdża płynnie)
        self.cur_heads = 1.0          # płynna liczba głów (1 na agenta)
        self.head_a = [1.0] + [0.0] * (self.MAXH - 1)   # aktywacja głów

    def _step_pips(self, dt):
        pass                          # licznik agentów pokazują głowy przejazdu

    def _waveform(self, phase):
        return _tri(phase)

    # --- sprite'y i warstwy ---------------------------------------------------
    def _sprites(self):
        s = self.scale
        spr = {
            "glow": self._glow_sprite(self.GLOW_COLOR, s),
            "hot": KF.hot_cell_sprite(int(self.cell_w * s), int(self.cell_h * s),
                                      color=self.HOT_COLOR),
            "attn": self._glow_sprite(self.ATTN_COLOR, s),
            "attn_speak": self._glow_sprite(self.ATTN_SPEAK, s),
        }
        if self.BACKING:
            spr["backing"] = KF.backing_sprite(
                int(self.w * s), int(self.h * s), [x * s for x in self._xs],
                self.glow_w * s, self.glow_h * s,
                bar_alpha=self.BAR_ALPHA, cell_alpha=self.CELL_ALPHA)
        return spr

    def _glow_sprite(self, color, s):
        """Świecący element diody: pionowa lampa (KITT) albo okrągła plama (Cylon)."""
        if self.LAMP:
            return KF.lamp_sprite(self.glow_w * s, self.glow_h * s, color)
        return glow_dot(self.glow_d * s, color, boost=1.5)

    def _layers(self):
        midy = self.h / 2.0
        specs = []
        if self.BACKING:                          # ciemny pas + oczodoły (Cylon)
            specs.append({"img": "backing", "w": self.w, "h": self.h,
                          "x": self.w / 2.0, "y": midy, "op": 1.0})
        self.i_glow, self.i_core, self.i_amber = [], [], []
        for x in self._xs:
            self.i_glow.append(len(specs))
            specs.append({"img": "glow", "w": self.glow_w, "h": self.glow_h,
                          "x": x, "y": midy, "op": self.FLOOR})
            self.i_core.append(len(specs))
            specs.append({"img": "hot", "w": self.cell_w, "h": self.cell_h,
                          "x": x, "y": midy, "op": 0.0})
            self.i_amber.append(len(specs))
            specs.append({"img": "attn", "w": self.glow_w, "h": self.glow_h,
                          "x": x, "y": midy, "op": 0.0})
        return specs

    # --- animacja ---------------------------------------------------------------
    def _enter(self, mode):
        # tylko aktywność steruje ruchem; uwaga (czekanie) zmienia sam kolor
        if mode == "think":
            self.amp_t, self.speed_t, self.bloom_t = 1.0, self.SPEED_THINK, 0.0
        elif mode == "speak":
            self.amp_t, self.speed_t, self.bloom_t = 0.0, self.SPEED_IDLE, 1.0
        else:                                     # idle — wolny przejazd
            self.amp_t, self.speed_t, self.bloom_t = 1.0, self.SPEED_IDLE, 0.0

    def _step(self, dt, now, level):
        k = 1.0 - math.exp(-dt / self.EASE_TAU)
        self.amp += (self.amp_t - self.amp) * k
        self.speed += (self.speed_t - self.speed) * k
        self.bloom += (self.bloom_t - self.bloom) * k
        mult = age_mult(self.snap.get("age", 0.0)) if self.mode == "think" else 1.0
        self.phase += self.speed * mult * dt
        hx = 0.5 + self.amp * self.SWEEP_HALF * self._waveform(self.phase)

        reach = (self.SPEAK_BASE + level * self.SPEAK_GAIN) * self.bloom
        if self.mode == "speak":
            tail_tau = self.SPEAK_TAU
        elif self.mode == "think":
            tail_tau = self.TAIL_TAU_THINK
        else:
            tail_tau = self.TAIL_TAU
        decay = math.exp(-dt / tail_tau)
        # UWAGA = tylko kolor: bramka wjeżdża/wyjeżdża, ruch bez zmian. Kolor
        # zależy od aktywności: inny gdy mówi (ATTN_SPEAK) niż gdy pracuje/idle.
        waiting = bool(self.snap.get("waiting"))
        self.attn_gate = ease_step(self.attn_gate, 1.0 if waiting else 0.0,
                                   dt, GATE_TAU)
        attn_key = "attn_speak" if self.mode == "speak" else "attn"
        sigma = self.HEAD_SIGMA

        # liczba „głów" = liczba agentów (płynnie), zbita grupa jadąca razem
        nbusy = max(1, min(self.MAXH, int(self.snap.get("busy", 1))))
        self.cur_heads = ease_step(self.cur_heads, float(nbusy), dt, 0.30)
        for k in range(self.MAXH):
            self.head_a[k] = ease_step(self.head_a[k],
                                       1.0 if k < nbusy else 0.0, dt, 0.30)
        half = (self.cur_heads - 1.0) / 2.0
        centers = [hx + (k - half) * self.HEAD_GAP for k in range(self.MAXH)]

        g = self.attn_gate
        led = self.led
        for i, p in enumerate(self._pos01):
            head = 0.0
            for k in range(self.MAXH):
                a = self.head_a[k]
                if a > 0.01:
                    dk = p - centers[k]
                    head = max(head, a * math.exp(-(dk / sigma) ** 2))
            d = p - hx
            flare = min(1.0, max(0.0, (reach - abs(d)) / self.SPEAK_EDGE))
            des = head if head > flare else flare
            led[i] = des if des > led[i] * decay else led[i] * decay
            if led[i] < 0.001:
                led[i] = 0.0
            v = min(1.0, led[i])
            # rdzeń liczony progowo, ale KRYCIE wygładzone (bez przeskoku 1->0)
            core_t = max(0.0, (v - self.CORE_THRESH) / (1.0 - self.CORE_THRESH))
            self.core[i] = ease_step(self.core[i], core_t, dt, 0.07)
            glow = self.FLOOR + (1.0 - self.FLOOR) * v
            # uwaga przemalowuje oko: czerwień/rdzeń gaśnie, kolor uwagi wchodzi
            self.op(self.i_glow[i], glow * (1.0 - g))
            self.op(self.i_core[i], self.core[i] * (1.0 - g))
            self.img(self.i_amber[i], attn_key)
            self.op(self.i_amber[i], glow * g)


class CylonTheme(KittTheme):
    """Cylon (Battlestar Galactica): czysta głęboka czerwień, szersze oko,
    sinusoidalny przejazd z zawieszeniem na krawędziach — bez rozgrzewania
    segmentów do bieli."""

    N_LED = 17
    LAMP = False                  # Cylon: okrągłe, rozmyte oko (nie segmenty)
    BACKING = True                # Cylon zostaje z tłem/oczodołami
    FLOOR = 0.10
    EDGE = 22.0
    HEAD_SIGMA = 0.11             # szersze, rozmyte oko
    CORE_THRESH = 0.80            # segmenty prawie się nie rozgrzewają
    SPEED_IDLE = 0.14
    SPEED_THINK = 0.45
    TAIL_TAU = 0.16
    TAIL_TAU_THINK = 0.24         # dłuższy, filmowy ogon
    GLOW_COLOR = (255, 8, 8)
    HOT_COLOR = (255, 60, 44)
    PIP_COLOR = (255, 8, 8)
    ATTN_COLOR = (255, 116, 16)  # Cylon: pomarańcz gdy czeka
    ATTN_SPEAK = ATTN_COLOR      # Cylon: TEN SAM pomarańcz też przy mowie

    def _waveform(self, phase):
        return math.sin(2.0 * math.pi * phase)   # płynne zawieszenie na skrajach
