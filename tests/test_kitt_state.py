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
    monkeypatch.setattr(KS, "ATTENTION_DIR", str(tmp_path / "attention.d"))
    # domyślnie: cisza (brak procesów audio)
    monkeypatch.setattr(KS, "_running_process_names", lambda: set())
    return tmp_path


def _config(paths, **overrides):
    cfg = {"voice": "Krzysztof"}
    cfg.update(overrides)
    (paths / "config.json").write_text(json.dumps(cfg))


def _marker(paths, dirname, name="s1", age=0.0):
    import time
    d = paths / dirname
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("123")
    if age:
        t = time.time() - age
        os.utime(f, (t, t))
    return f


def _busy(paths, name="s1", age=0.0):
    return _marker(paths, "busy.d", name, age)


def _attention(paths, name="s1", age=0.0):
    return _marker(paths, "attention.d", name, age)


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


# --- uwaga (czekanie na usera) to OSOBNA oś: waiting, nie mode ---------------

def test_waiting_flag_when_marker_fresh(paths):
    _config(paths)
    _attention(paths)
    # uwaga nie zmienia ruchu (mode=idle), tylko podnosi flagę waiting
    assert KS.current_mode() == "idle"
    assert KS.snapshot()["waiting"] is True


def test_waiting_orthogonal_to_think(paths):
    _config(paths)
    _busy(paths)              # inny agent pracuje -> ruch think
    _attention(paths)         # i ktoś czeka -> waiting
    snap = KS.snapshot()
    assert snap["mode"] == "think"      # RUCH wg aktywności (szybki)
    assert snap["waiting"] is True      # KOLOR wg czekania


def test_speak_activity_with_waiting(paths, monkeypatch):
    _config(paths)
    _attention(paths)
    _audio(monkeypatch, on=True)
    snap = KS.snapshot()
    assert snap["mode"] == "speak" and snap["waiting"] is True


def test_stale_attention_not_waiting(paths):
    _config(paths)
    _attention(paths, age=KS.ATTENTION_STALE_SEC + 60)
    assert KS.snapshot()["waiting"] is False


# --- licznik sesji i wiek pracy ----------------------------------------------

def test_busy_count_counts_fresh_markers_only(paths):
    _config(paths)
    _busy(paths, "a")
    _busy(paths, "b")
    _busy(paths, "dead", age=KS.BUSY_STALE_SEC + 60)
    assert KS.busy_count() == 2


def test_busy_count_zero_without_dir(paths):
    assert KS.busy_count() == 0


def test_busy_age_is_oldest_fresh_marker(paths):
    _config(paths)
    _busy(paths, "young", age=10)
    _busy(paths, "old", age=120)
    age = KS.busy_age()
    assert 115 <= age <= 130


def test_busy_age_zero_when_idle(paths):
    _config(paths)
    assert KS.busy_age() == 0.0


def test_snapshot_shape(paths):
    _config(paths)
    _busy(paths, "a")
    _busy(paths, "b")
    snap = KS.snapshot()
    assert snap["mode"] == "think"
    assert snap["busy"] == 2
    assert snap["age"] >= 0.0


def test_snapshot_mode_none_when_disabled(paths):
    _config(paths, knight_rider=False)
    assert KS.snapshot()["mode"] is None


# --- wybór motywu z configu ---------------------------------------------------

def test_theme_name_default_spark(paths):
    _config(paths)
    assert KS.theme_name() == "spark"


def test_theme_name_from_config_normalized(paths):
    _config(paths, overlay_theme=" HAL ")
    assert KS.theme_name() == "hal"
