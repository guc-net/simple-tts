"""Testy kontraktu motywów nakładki (overlay/themes/) — bez GUI.

Motyw to czysta logika PIL + arytmetyka: host (kitt_overlay.py) tylko
konwertuje sprite'y do CGImage i aplikuje aktualizacje na CALayer-ach.
Testowany kontrakt:
  sprites()    -> dict nazwa -> PIL.Image (RGBA)
  layers()     -> lista specyfikacji warstw {img,w,h,x,y,op}
  enter_mode() -> reset celów animacji dla trybu
  step()       -> lista aktualizacji (idx, "op"|"pos"|"img", wartość)
  fps()        -> tempo renderu dla trybu
  invalidate() -> zapomnij zaaplikowane wartości (pełny zapis po wybudzeniu)
  pip_indices  -> warstwy kropek licznika sesji (fleet)
"""

import os
import sys

import pytest

pytest.importorskip("PIL")

OVERLAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overlay")
sys.path.insert(0, OVERLAY_DIR)

from themes import THEME_NAMES, get_theme  # noqa: E402

W, H, SCALE = 520, 30, 2
MODES = ("idle", "think", "speak", "attention")
SNAP = {"busy": 1, "age": 0.0}


def _mk(name):
    return get_theme(name, W, H, SCALE)


def _run(theme, mode, frames=90, level=0.0, snap=SNAP, t0=100.0):
    theme.enter_mode(mode, snap)
    ups, now = [], t0
    for _ in range(frames):
        now += 1.0 / theme.fps(mode)
        ups.extend(theme.step(1.0 / theme.fps(mode), now, level, snap))
    return ups


def test_registry_has_all_themes():
    assert set(THEME_NAMES) >= {"kitt", "cylon", "spark"}


def test_unknown_theme_falls_back_to_kitt():
    assert type(_mk("no-such-theme")) is type(_mk("kitt"))


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
def test_sprites_are_rgba_images(name):
    from PIL import Image
    spr = _mk(name).sprites()
    assert spr, "motyw bez sprite'ów"
    for key, img in spr.items():
        assert isinstance(img, Image.Image), key
        assert img.mode == "RGBA", key


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
def test_layers_reference_existing_sprites(name):
    t = _mk(name)
    keys = set(t.sprites().keys())
    specs = t.layers()
    assert specs
    for spec in specs:
        assert spec["img"] in keys
        assert 0.0 <= spec["op"] <= 1.0
        assert 0.0 <= spec["x"] <= W
        assert spec["w"] > 0 and spec["h"] > 0


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
@pytest.mark.parametrize("mode", MODES)
def test_step_updates_are_valid_and_animate(name, mode):
    t = _mk(name)
    n = len(t.layers())
    keys = set(t.sprites().keys())
    ups = _run(t, mode)
    assert ups, f"{name}/{mode}: martwa animacja (zero aktualizacji)"
    for idx, prop, val in ups:
        assert 0 <= idx < n
        assert prop in ("op", "pos", "img", "xf")
        if prop == "op":
            assert 0.0 <= val <= 1.0
        elif prop == "img":
            assert val in keys
        elif prop == "pos":
            assert len(val) == 2
        else:                                     # xf — (kąt, sx, sy)
            assert len(val) == 3


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
def test_invalidate_forces_full_reemit(name):
    t = _mk(name)
    _run(t, "idle", frames=30)
    t.invalidate()
    ups = t.step(0.05, 999.0, 0.0, SNAP)
    assert ups, "po invalidate() pierwsza klatka musi zapisać stan warstw"


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
def test_fps_sane_for_every_mode(name):
    t = _mk(name)
    for mode in MODES:
        assert 5 <= t.fps(mode) <= 60


@pytest.mark.parametrize("name", ["kitt", "cylon", "spark"])
def test_fleet_pips_hidden_in_idle(name):
    t = _mk(name)
    snap = {"busy": 0, "age": 0.0}
    t.enter_mode("idle", snap)
    t.invalidate()
    for idx, prop, val in t.step(0.05, 100.0, 0.0, snap):
        if prop == "op" and idx in t.pip_indices:
            assert val < 0.05
