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
    monkeypatch.setattr(KS, "BUSY_DIR", str(tmp_path / "busy.d"))
    # domyślnie: cisza (brak procesów audio)
    monkeypatch.setattr(KS, "_running_process_names", lambda: set())
    return tmp_path


def _config(paths, **overrides):
    cfg = {"voice": "Krzysztof"}
    cfg.update(overrides)
    (paths / "config.json").write_text(json.dumps(cfg))


def _busy(paths, name="s1"):
    d = paths / "busy.d"
    d.mkdir(exist_ok=True)
    (d / name).write_text("123")


def _audio(monkeypatch, on=True):
    monkeypatch.setattr(KS, "_tts_active", lambda: on)
    monkeypatch.setattr(KS, "_running_process_names",
                        lambda: {"afplay"} if on else set())


def test_mode_none_when_not_configured(paths):
    assert KS.current_mode() is None


def test_mode_none_when_knight_rider_off(paths):
    _config(paths, knight_rider=False)
    assert KS.current_mode() is None


def test_idle_when_enabled_and_quiet(paths):
    _config(paths)
    assert KS.current_mode() == "idle"


def test_think_when_any_session_busy(paths):
    _config(paths)
    _busy(paths)
    assert KS.current_mode() == "think"


def test_idle_when_busy_dir_empty(paths):
    _config(paths)
    (paths / "busy.d").mkdir()
    assert KS.current_mode() == "idle"


def test_speak_when_audio_playing(paths, monkeypatch):
    _config(paths)
    _busy(paths)                          # nawet gdy ktoś myśli...
    _audio(monkeypatch, on=True)          # ...mowa wygrywa
    assert KS.current_mode() == "speak"


def test_stale_busy_marker_ignored(paths):
    _config(paths)
    d = paths / "busy.d"
    d.mkdir()
    old = d / "dead"
    old.write_text("x")
    os.utime(old, (0, 0))                 # bardzo stary -> osierocony
    assert KS.current_mode() == "idle"


def test_is_speaking_true_on_afplay(paths, monkeypatch):
    _audio(monkeypatch, on=True)
    assert KS.is_speaking() is True


def test_is_speaking_false_when_silent(paths):
    assert KS.is_speaking() is False


def test_no_speak_without_tts_process(paths, monkeypatch):
    # afplay innej apki gra, ale nie ma naszego procesu TTS -> nie "speak"
    _config(paths)
    monkeypatch.setattr(KS, "_running_process_names", lambda: {"afplay"})
    assert KS.current_mode() == "idle"


def test_tts_active_gate_true_when_pid_alive(paths, monkeypatch):
    (paths / "state.json").write_text(json.dumps({"pid": 4242, "ts": 0}))
    monkeypatch.setattr(KS.os, "kill", lambda pid, sig: None)
    assert KS._tts_active() is True
