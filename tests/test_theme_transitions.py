"""Testy płynności przejść między trybami motywów nakładki.

Kontrakt: zmiana trybu NIGDY nie powoduje skokowej zmiany obrazu — jasności
wjeżdżają po bramkach z easingiem, zmiany koloru to krosfejd albo stopniowa
wymiana treści (per segment / per kolumna), nigdy przebarwienie całości
w jednej klatce.
"""

import os
import sys

import pytest

pytest.importorskip("PIL")

OVERLAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overlay")
sys.path.insert(0, OVERLAY_DIR)

from themes import get_theme  # noqa: E402

W, H, SCALE = 520, 30, 2
SNAP = {"busy": 1, "age": 0.0}


def _mk(name):
    return get_theme(name, W, H, SCALE)


def _settle(t, mode, snap=SNAP, seconds=4.0, t0=100.0, level=0.0):
    """Ustabilizuj motyw w trybie; zwróć (now, stan op per idx)."""
    t.enter_mode(mode, snap)
    fps = t.fps(mode)
    now = t0
    ops = {i: spec["op"] for i, spec in enumerate(t.layers())}
    imgs = {i: spec["img"] for i, spec in enumerate(t.layers())}
    for _ in range(int(seconds * fps)):
        now += 1.0 / fps
        for idx, prop, val in t.step(1.0 / fps, now, level, snap):
            if prop == "op":
                ops[idx] = val
            elif prop == "img":
                imgs[idx] = val
    return now, ops, imgs


def _steps(t, mode, now, seconds, snap=SNAP, level=0.0, ops=None, imgs=None):
    """Krok po kroku w (już ustawionym) trybie; zwraca (now, ops, imgs,
    lista aktualizacji z PIERWSZEGO kroku)."""
    fps = t.fps(mode)
    first = None
    for _ in range(max(1, int(seconds * fps))):
        now += 1.0 / fps
        ups = t.step(1.0 / fps, now, level, snap)
        if first is None:
            first = ups
        for idx, prop, val in ups:
            if prop == "op" and ops is not None:
                ops[idx] = val
            elif prop == "img" and imgs is not None:
                imgs[idx] = val
    return now, first


# --- bramki attention wjeżdżają, nie wskakują --------------------------------

@pytest.mark.parametrize("name,attr", [("kitt", "i_amber"), ("cylon", "i_amber")])
def test_amber_ramps_in_on_attention(name, attr):
    t = _mk(name)
    now, ops, imgs = _settle(t, "think")
    idxs = getattr(t, attr)
    # przełączenie wyrównane do okna błysku (blink(now)==1 dla now%1.2<0.14)
    now = now - (now % 1.2) + 1.2
    t.enter_mode("attention", SNAP)
    now, first = _steps(t, "attention", now, 0.0, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx in idxs:
            assert val < 0.35, "bursztyn ma wjechać po bramce, nie wskoczyć"
    # po ~2 s bramka otwarta: w oknie błysku bursztyn jest już jasny
    best = 0.0
    fps = t.fps("attention")
    for _ in range(int(2.5 * fps)):
        now += 1.0 / fps
        for idx, prop, val in t.step(1.0 / fps, now, 0.0, SNAP):
            if prop == "op" and idx in idxs:
                best = max(best, val)
    assert best > 0.6


def test_hal_ring_ramps_in_on_attention():
    t = _mk("hal")
    now, ops, imgs = _settle(t, "think")
    now = now - (now % 1.2) + 1.2
    t.enter_mode("attention", SNAP)
    now, first = _steps(t, "attention", now, 0.0, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx == t.i_ring:
            assert val < 0.35


def test_hal_brightness_eases_between_modes():
    t = _mk("hal")
    now, ops, imgs = _settle(t, "idle")
    before = ops[t.i_glow]
    t.enter_mode("think", SNAP)
    now, first = _steps(t, "think", now, 0.0, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx == t.i_glow:
            assert abs(val - before) < 0.15, "jasność oka ma płynąć, nie skakać"


def test_ekg_dot_fades_out_after_speak():
    t = _mk("ekg")
    now, ops, imgs = _settle(t, "speak", level=0.0)
    t.enter_mode("idle", SNAP)
    now, first = _steps(t, "idle", now, 0.0, ops=ops, imgs=imgs)
    dot = [val for idx, prop, val in first if prop == "op" and idx == t.i_dot]
    assert dot and dot[0] > 0.05, "kropka ma zgasnąć płynnie, nie z klatki na klatkę"


# --- matrix: krycie/tempo płyną, kolor wymienia się kolumna po kolumnie ------

def test_matrix_opacity_eases_on_mode_change():
    t = _mk("matrix")
    now, ops, imgs = _settle(t, "idle")
    strip_idx = set(range(2 * t.n_cols))
    before = max(ops[i] for i in strip_idx)
    t.enter_mode("think", SNAP)
    now, first = _steps(t, "think", now, 0.0, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx in strip_idx:
            assert abs(val - before) < 0.15


def test_matrix_recolors_column_by_column():
    t = _mk("matrix")
    now, ops, imgs = _settle(t, "think")
    strip_idx = set(range(2 * t.n_cols))
    t.enter_mode("attention", SNAP)
    now, first = _steps(t, "attention", now, 0.0, ops=ops, imgs=imgs)
    swapped_first = sum(1 for idx, prop, val in first
                        if prop == "img" and idx in strip_idx and "astrip" in val)
    assert swapped_first <= 2 * t.n_cols * 0.25, \
        "kolor ma się wymieniać kolumnami, nie wszystkie naraz"
    now, _ = _steps(t, "attention", now, 3.0, ops=ops, imgs=imgs)
    amber = sum(1 for i in strip_idx if "astrip" in imgs[i])
    assert amber == 2 * t.n_cols, "po paru sekundach cały deszcz jest bursztynowy"


# --- spark: soczewka krosfejdem między dwiema warstwami -----------------------

def test_spark_attention_is_a_crossfade():
    t = _mk("spark")
    now, ops, imgs = _settle(t, "think")
    t.enter_mode("attention", SNAP)
    now, first = _steps(t, "attention", now, 0.0, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx == t.i_lens_a:
            assert val < 0.3, "bursztynowa soczewka ma wjechać krosfejdem"
    now, _ = _steps(t, "attention", now, 2.5, ops=ops, imgs=imgs)
    assert ops[t.i_lens_a] > 0.45
    assert ops[t.i_lens_g] < 0.35


# --- kropki licznika sesji też płyną ------------------------------------------

@pytest.mark.parametrize("name", ["kitt", "cylon", "hal", "ekg", "matrix", "spark"])
def test_pips_fade_in(name):
    t = _mk(name)
    snap0 = {"busy": 0, "age": 0.0}
    snap3 = {"busy": 3, "age": 0.0}
    now, ops, imgs = _settle(t, "idle", snap=snap0)
    t.enter_mode("think", snap3)
    now, first = _steps(t, "think", now, 0.0, snap=snap3, ops=ops, imgs=imgs)
    for idx, prop, val in first:
        if prop == "op" and idx in t.pip_indices:
            assert val < 0.4, "kropki licznika mają wjechać, nie wskoczyć"
    now, _ = _steps(t, "think", now, 2.0, snap=snap3, ops=ops, imgs=imgs)
    lit = [i for i in t.pip_indices if ops[i] > 0.6]
    assert len(lit) == 3
