"""Sprite'y nakładki KITT (PIL -> RGBA) — rysowane raz, animuje Core Animation.

  dot_sprite     -> czerwona świecąca kropka (poświata diody)
  hot_cell_sprite-> biało-gorąca CAŁA cela (zaokrąglony prostokąt) — zapala się
                    przy pełnej jasności, jak dwa prawe segmenty w referencji
  backing_sprite -> jedna statyczna listwa: ciemny pas + wtopione obudowy diod
                    (półprzezroczysta — tło prześwituje, bo to overlay)

Alfa niesie świecenie; warstwy komponowane zwykłym source-over (bez filtrów
addytywnych — te wymuszały kosztowny offscreen rendering w WindowServerze).
"""

import math

from PIL import Image, ImageDraw

CORE = (225, 28, 10)      # głęboka nasycona czerwień diod (jak w KITT)
HOT = (255, 116, 32)      # rozgrzany segment: intensywny pomarańczowo-czerwony


def dot_sprite(px, boost=1.6):
    """Pojedyncza świecąca kropka jako RGBA (przezroczyste tło): jasny środek,
    miękko gasnące krawędzie."""
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
            p[x, y] = (CORE[0], CORE[1], CORE[2],
                       max(0, min(255, int(255 * a * boost))))
    return img


def hot_cell_sprite(w, h, color=HOT):
    """Rozgrzana cała cela (RGBA): zaokrąglony prostokąt, intensywny
    pomarańczowo-czerwony środek przechodzący w głęboką czerwień na brzegu.
    Widoczna dopiero przy dużej jasności — jak najjaśniejsze segmenty w KITT."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    p = img.load()
    cx, cy = w / 2.0, h / 2.0
    # promień narożnika i miękkość brzegu w px
    rad = h * 0.32
    soft = max(2.0, h * 0.22)
    for y in range(h):
        for x in range(w):
            # odległość od brzegu zaokrąglonego prostokąta (SDF)
            qx = abs(x - cx) - (w / 2.0 - rad)
            qy = abs(y - cy) - (h / 2.0 - rad)
            dist = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - rad
            if dist >= 0:
                a = 0.0
            else:
                a = min(1.0, -dist / soft)
            # pomarańcz tylko w głębi celi; brzegi w głęboką czerwień poświaty
            t = max(0.0, (a - 0.45) / 0.55) ** 1.6
            cr = int(color[0] * t + CORE[0] * (1 - t))
            cg = int(color[1] * t + CORE[1] * (1 - t))
            cb = int(color[2] * t + CORE[2] * (1 - t))
            p[x, y] = (min(255, cr), min(255, cg), min(255, cb),
                       int(255 * a))
    return img


def backing_sprite(w, h, xs, cell_w, cell_h, bar_alpha=0.12, cell_alpha=0.18):
    """Cała statyczna listwa jako JEDEN obraz (RGBA): delikatny ciemny pas
    + obudowy diod w pozycjach `xs` (px). Bez obrysów, mocno przezroczysta —
    to overlay nad desktopem, tło ma być dobrze widoczne."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = cell_w * 0.45
    x0, x1 = xs[0] - cell_w / 2 - pad, xs[-1] + cell_w / 2 + pad
    y0, y1 = (h - cell_h) / 2 - pad * 0.35, (h + cell_h) / 2 + pad * 0.35
    if bar_alpha > 0:
        d.rounded_rectangle([x0, y0, x1, y1], radius=int((y1 - y0) * 0.30),
                            fill=(8, 3, 3, int(255 * bar_alpha)))
    if cell_alpha > 0:
        rad = int(cell_h * 0.32)
        for x in xs:
            d.rounded_rectangle(
                [x - cell_w / 2, (h - cell_h) / 2,
                 x + cell_w / 2, (h + cell_h) / 2],
                radius=rad, fill=(34, 12, 10, int(255 * cell_alpha)))
    return img
