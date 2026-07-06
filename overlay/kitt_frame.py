"""Renderer klatek KITT — trzy tryby, wg ducha Griefed/LarsonScanner.

  idle   -> pojedyncza kropka jeździ prawo<->lewo z gasnącym ogonem
  think  -> dwie kropki nerwowo gonią się w środku
  speak  -> modulator głosu: symetryczny blok pulsuje od środka

render(W, H, t, mode) -> PIL.Image (RGB, czarne tło). Wymaga tylko PIL.
Addytywny glow: jasny środek, miękkie krawędzie.
"""

import math

from PIL import Image, ImageChops

# --- parametry -------------------------------------------------------------
SWEEP_SEC = 1.6            # czas przejazdu kropki (idle)
ELEM_W = 0.045            # bazowa jednostka rozstawu ~ W/22
CORE = (255, 55, 35)      # kolor świecącego rdzenia
_SPR = {}


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _sprite(rad, h):
    key = (round(rad, 1), h)
    if key in _SPR:
        return _SPR[key]
    rx = max(2.0, rad)
    ry = max(2.0, h / 2.0 * 0.90)
    w, ht = int(rx * 2), int(ry * 2)
    spr = Image.new("RGB", (w, ht), (0, 0, 0))
    px = spr.load()
    for y in range(ht):
        for x in range(w):
            nx, ny = (x - rx) / rx, (y - ry) / ry
            r = math.sqrt(nx * nx + ny * ny)
            if r >= 1.0:
                a = 0.0
            elif r <= 0.40:
                a = 1.0
            else:
                a = 1.0 - (r - 0.40) / 0.60
            a *= a
            px[x, y] = (int(CORE[0] * a), int(CORE[1] * a), int(CORE[2] * a))
    _SPR[key] = (spr, rx, ry)
    return _SPR[key]


def _glow(frame, spr, rx, ry, cx, cy, bright):
    if bright <= 0.01:
        return frame
    W, H = frame.size
    s = spr if bright >= 0.999 else spr.point(lambda v: int(v * bright))
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    layer.paste(s, (int(cx - rx), int(cy - ry)))
    return ImageChops.add(frame, layer)


# --- tryby -----------------------------------------------------------------
def _idle(frame, t, spr, rx, ry, ew):
    """Kropka + gasnący ogon = przeszłe pozycje głowy (zawsze w kadrze)."""
    W, H = frame.size
    cy = H / 2.0
    margin = rx + 8
    span = W - 2 * margin
    period = 2 * SWEEP_SEC

    def pos_at(tt):
        ph = (tt % period) / SWEEP_SEC
        return margin + (ph if ph <= 1.0 else 2.0 - ph) * span

    tail_n, tail_dt = 7, 0.055
    for k in range(tail_n, 0, -1):                     # ogon: coraz starsze pozycje
        b = (1.0 - k / float(tail_n + 1)) ** 1.7
        frame = _glow(frame, spr, rx, ry, pos_at(t - k * tail_dt), cy, b * 0.95)
    return _glow(frame, spr, rx, ry, pos_at(t), cy, 1.0)  # jasna głowa


def _think(frame, t, spr, rx, ry, ew):
    """Dwie kropki nerwowo gonią się w środku (szybko, z krzyżowaniem)."""
    W, H = frame.size
    cy = H / 2.0
    margin = rx + 2
    amp = (W / 2.0 - margin) * 0.92
    s = math.sin(t * 6.2)                              # nerwowe tempo
    for sign in (1, -1):
        cx = W / 2.0 + sign * amp * s
        for k in range(3, 0, -1):                      # krótki ogonek
            frame = _glow(frame, spr, rx, ry,
                          cx - sign * amp * 0.10 * k, cy, (1 - k / 4.0) * 0.6)
        frame = _glow(frame, spr, rx, ry, cx, cy, 1.0)
    return frame


def _speak(frame, t, spr, rx, ry, ew):
    """Modulator głosu: symetryczny blok pulsuje od środka na zewnątrz."""
    W, H = frame.size
    cy = H / 2.0
    center = W / 2.0
    margin = rx + 2
    env = _clamp(0.5 + 0.30 * math.sin(t * 7.3)
                 + 0.12 * math.sin(t * 17.1 + 1.3)
                 + 0.08 * math.sin(t * 3.1 + 0.7))
    reach = env * (center - margin)
    x = 0.0
    while x <= reach + ew:
        b = min(0.9, _clamp(1.0 - (x / (reach + 1.0)) * 0.55))
        for sgn in ((0,) if x < ew * 0.4 else (1, -1)):
            frame = _glow(frame, spr, rx, ry, center + sgn * x, cy, b)
        x += ew * 0.85
    return frame


_MODES = {"idle": _idle, "think": _think, "speak": _speak}


def render(W, H, t, mode="idle"):
    frame = Image.new("RGB", (W, H), (0, 0, 0))
    ew = W * ELEM_W
    spr, rx, ry = _sprite(ew, H)
    fn = _MODES.get(mode, _idle)
    return fn(frame, t, spr, rx, ry, ew)
