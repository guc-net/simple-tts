"""Testy obwiedni audio dla nakładki KITT (edge_speak._envelope / zapis stanu)."""

import json
import os
import sys

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import edge_speak as es  # noqa: E402


class _Run:
    def __init__(self, out):
        self.stdout = out


def test_envelope_normalizes_db_to_unit(monkeypatch):
    lines = [
        "lavfi.astats.Overall.RMS_level=-15.0",   # szczyt -> 1.0
        "lavfi.astats.Overall.RMS_level=-50.0",   # dolina -> 0.0
        "lavfi.astats.Overall.RMS_level=-32.5",   # środek -> 0.5
        "lavfi.astats.Overall.RMS_level=-inf",    # cisza -> 0.0
        "some unrelated ffmpeg line",
    ]
    monkeypatch.setattr(es.subprocess, "run",
                        lambda *a, **k: _Run("\n".join(lines)))
    assert es._envelope("x.mp3") == [1.0, 0.0, 0.5, 0.0]


def test_compute_envelope_returns_dt_and_env(monkeypatch):
    monkeypatch.setattr(es.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(es, "_envelope", lambda p: [0.1, 0.9, 0.4])
    assert es._compute_envelope("x.mp3") == (es._ENV_DT, [0.1, 0.9, 0.4])


def test_compute_envelope_none_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(es.shutil, "which", lambda n: None)
    assert es._compute_envelope("x.mp3") is None


def test_compute_envelope_none_on_empty(monkeypatch):
    monkeypatch.setattr(es.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(es, "_envelope", lambda p: [])
    assert es._compute_envelope("x.mp3") is None


def test_write_speak_state_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_state([0.1, 0.9, 0.4], 0.04)
    d = json.load(open(tmp_path / "speak.json"))
    assert d["dt"] == 0.04
    assert d["env"] == [0.1, 0.9, 0.4]
    assert isinstance(d["start"], (int, float))


def test_write_speak_state_noop_on_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_state([], 0.04)
    assert not (tmp_path / "speak.json").exists()


def test_write_speak_state_prepends_lead(monkeypatch, tmp_path):
    # gdy przed głosem gra intro syreny, obwiednia dostaje ciszę z przodu
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_state([0.5, 0.6], 0.1, lead=0.3)    # 3 zera (0.3/0.1) + głos
    d = json.load(open(tmp_path / "speak.json"))
    assert d["env"] == [0.0, 0.0, 0.0, 0.5, 0.6]


# --- obwiednia z cache (liczona raz na frazę, obok pliku audio) -------------

def _epayload(**over):
    p = {"edge_voice": "V", "edge_rate": "+0%", "text": "hej"}
    p.update(over)
    return p


def test_cached_envelope_computes_and_stores_on_miss(monkeypatch, tmp_path):
    monkeypatch.setattr(es.ac, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(es, "_compute_envelope", lambda p: (0.04, [0.3, 0.8]))
    payload = _epayload()
    assert es._cached_envelope(payload, "voice.mp3") == (0.04, [0.3, 0.8])
    # zapisana obok audio -> kolejny odczyt bez ffmpeg
    assert es.ac.read_env(es.ac.key_for(payload)) == (0.04, [0.3, 0.8])


def test_cached_envelope_hit_skips_recompute(monkeypatch, tmp_path):
    monkeypatch.setattr(es.ac, "CACHE_DIR", str(tmp_path / "cache"))
    payload = _epayload()
    es.ac.store_env(es.ac.key_for(payload), 0.04, [0.9])

    def boom(p):
        raise AssertionError("trafienie w cache nie powinno liczyć obwiedni")

    monkeypatch.setattr(es, "_compute_envelope", boom)
    assert es._cached_envelope(payload, "voice.mp3") == (0.04, [0.9])


# --- _play_speech: obwiednia dla KAŻDEGO motywu, gdy nakładka włączona ------

def test_play_speech_writes_state_when_overlay_on(monkeypatch, tmp_path):
    # spark: brak syreny (_mix_kitt None), a obwiednia i tak trafia na dysk
    monkeypatch.setattr(es, "_mix_kitt", lambda p, pl: None)
    monkeypatch.setattr(es, "_play", lambda p: True)
    monkeypatch.setattr(es, "_compute_envelope", lambda p: (0.04, [0.2, 0.9]))
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    assert es._play_speech("voice.mp3", {"envelope": True, "intro_sound": "none"}) is True
    d = json.load(open(tmp_path / "speak.json"))
    assert (d["dt"], d["env"]) == (0.04, [0.2, 0.9])   # bez lead (brak miksu)


def test_play_speech_skips_envelope_when_overlay_off(monkeypatch, tmp_path):
    monkeypatch.setattr(es, "_mix_kitt", lambda p, pl: None)
    monkeypatch.setattr(es, "_play", lambda p: True)

    def boom(p):
        raise AssertionError("nakładka off -> obwiednia nie powinna być liczona")

    monkeypatch.setattr(es, "_compute_envelope", boom)
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._play_speech("voice.mp3", {"envelope": False})
    assert not (tmp_path / "speak.json").exists()


def test_play_speech_uses_passed_env_without_recompute(monkeypatch, tmp_path):
    monkeypatch.setattr(es, "_mix_kitt", lambda p, pl: None)
    monkeypatch.setattr(es, "_play", lambda p: True)

    def boom(p):
        raise AssertionError("env podany z góry (cache) -> bez ponownego liczenia")

    monkeypatch.setattr(es, "_compute_envelope", boom)
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._play_speech("voice.mp3", {"envelope": True}, env=(0.04, [0.7]))
    assert json.load(open(tmp_path / "speak.json"))["env"] == [0.7]


def test_play_speech_prepends_intro_lead_when_mixed(monkeypatch, tmp_path):
    # KITT: gra miks z syreną -> obwiednia dosunięta o intro (_INTRO/dt zer)
    monkeypatch.setattr(es, "_mix_kitt", lambda p, pl: "mixed.mp3")
    monkeypatch.setattr(es, "_play", lambda p: True)
    monkeypatch.setattr(es.os, "unlink", lambda p: None)
    monkeypatch.setattr(es, "_compute_envelope", lambda p: (0.1, [0.5, 0.6]))
    monkeypatch.setattr(es, "_INTRO", 0.2)
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._play_speech("voice.mp3", {"envelope": True, "intro_sound": "kitt"})
    assert json.load(open(tmp_path / "speak.json"))["env"] == [0.0, 0.0, 0.5, 0.6]
