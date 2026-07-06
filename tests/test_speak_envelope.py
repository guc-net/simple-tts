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


def test_write_speak_envelope_writes_state(monkeypatch, tmp_path):
    monkeypatch.setattr(es.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(es, "_envelope", lambda p: [0.1, 0.9, 0.4])
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_envelope("x.mp3")
    d = json.load(open(tmp_path / "speak.json"))
    assert d["dt"] == es._ENV_DT
    assert d["env"] == [0.1, 0.9, 0.4]
    assert isinstance(d["start"], (int, float))


def test_write_speak_envelope_noop_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(es.shutil, "which", lambda n: None)
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_envelope("x.mp3")
    assert not (tmp_path / "speak.json").exists()


def test_write_speak_envelope_noop_on_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(es.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(es, "_envelope", lambda p: [])
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_envelope("x.mp3")
    assert not (tmp_path / "speak.json").exists()


def test_write_speak_envelope_prepends_lead(monkeypatch, tmp_path):
    # gdy przed głosem gra intro syreny, obwiednia dostaje ciszę z przodu
    monkeypatch.setattr(es.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    monkeypatch.setattr(es, "_envelope", lambda p: [0.5, 0.6])
    monkeypatch.setattr(es, "_ENV_DT", 0.1)
    monkeypatch.setattr(es, "SPEAK_STATE_PATH", str(tmp_path / "speak.json"))
    es._write_speak_envelope("voice.mp3", lead=0.3)     # 3 zera (0.3/0.1) + głos
    d = json.load(open(tmp_path / "speak.json"))
    assert d["env"] == [0.0, 0.0, 0.0, 0.5, 0.6]
