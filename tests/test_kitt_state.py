"""Testy logiki trybu nakładki KITT (overlay/kitt_state.py) — stdlib, bez GUI."""

import json
import os
import sys

import pytest

OVERLAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "overlay")
sys.path.insert(0, OVERLAY_DIR)

import kitt_state as KS  # noqa: E402


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(KS, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(KS, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(KS, "BUSY_PATH", str(tmp_path / "busy"))
    return tmp_path


def _config(paths, **overrides):
    cfg = {"voice": "Krzysztof"}
    cfg.update(overrides)
    (paths / "config.json").write_text(json.dumps(cfg))


def test_mode_none_when_not_configured(paths):
    assert KS.current_mode() is None


def test_mode_none_when_knight_rider_off(paths):
    _config(paths, knight_rider=False)
    assert KS.current_mode() is None


def test_idle_when_enabled_and_quiet(paths):
    _config(paths)                       # knight_rider domyślnie True
    assert KS.current_mode() == "idle"


def test_think_when_busy(paths):
    _config(paths)
    (paths / "busy").write_text("1")
    assert KS.current_mode() == "think"


def test_idle_when_busy_zero(paths):
    _config(paths)
    (paths / "busy").write_text("0")
    assert KS.current_mode() == "idle"


def test_speak_overrides_busy(paths, monkeypatch):
    _config(paths)
    (paths / "busy").write_text("1")
    (paths / "state.json").write_text(json.dumps({"pid": 4242, "ts": 0}))
    monkeypatch.setattr(KS.os, "kill", lambda pid, sig: None)     # PID żyje

    class R:
        stdout = "/usr/bin/say -v Krzysztof cześć"

    monkeypatch.setattr(KS.subprocess, "run", lambda *a, **k: R())
    assert KS.current_mode() == "speak"


def test_speak_detects_edge_helper(paths, monkeypatch):
    _config(paths)
    (paths / "state.json").write_text(json.dumps({"pid": 99, "ts": 0}))
    monkeypatch.setattr(KS.os, "kill", lambda pid, sig: None)

    class R:
        stdout = "/usr/local/bin/python3 /x/hooks/edge_speak.py"

    monkeypatch.setattr(KS.subprocess, "run", lambda *a, **k: R())
    assert KS.is_speaking() is True


def test_not_speaking_when_pid_dead(paths, monkeypatch):
    _config(paths)
    (paths / "state.json").write_text(json.dumps({"pid": 4242, "ts": 0}))

    def dead(pid, sig):
        raise OSError()

    monkeypatch.setattr(KS.os, "kill", dead)
    assert KS.current_mode() == "idle"


def test_not_speaking_when_other_process(paths, monkeypatch):
    _config(paths)
    (paths / "state.json").write_text(json.dumps({"pid": 5, "ts": 0}))
    monkeypatch.setattr(KS.os, "kill", lambda pid, sig: None)

    class R:
        stdout = "/usr/bin/vim notes.txt"          # nie nasz proces

    monkeypatch.setattr(KS.subprocess, "run", lambda *a, **k: R())
    assert KS.is_speaking() is False
