"""Tests for edge_speak.py — the detached edge-tts helper: it should play the
synthesized mp3 on success and fall back to local `say` on any failure."""

import json

import edge_speak


class FakeCompleted:
    def __init__(self, returncode=0):
        self.returncode = returncode


def _payload(**overrides):
    p = {"edge_voice": "pl-PL-MarekNeural", "edge_rate": "+0%",
         "text": "dzień dobry", "say_voice": "Krzysztof", "say_rate": "220"}
    p.update(overrides)
    return p


def _patch_common(monkeypatch, runner):
    """Wire up env payload, a recording subprocess.run, and a non-empty mp3."""
    runs = []

    def fake_run(args, **kwargs):
        runs.append(args)
        return runner(args, **kwargs)

    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD", json.dumps(_payload()))
    monkeypatch.setattr(edge_speak.subprocess, "run", fake_run)
    monkeypatch.setattr(edge_speak.os.path, "getsize", lambda p: 4096)
    monkeypatch.setattr(edge_speak.os, "unlink", lambda p: None)
    return runs


def test_synthesizes_then_plays(monkeypatch):
    runs = _patch_common(monkeypatch, lambda args, **kw: FakeCompleted(0))
    edge_speak.main()
    assert runs[0][:2] == ["uvx", "edge-tts"]
    assert "pl-PL-MarekNeural" in runs[0]
    assert runs[1][0] == "afplay"  # plays the result, no say fallback


def test_falls_back_to_say_when_uvx_missing(monkeypatch):
    def runner(args, **kw):
        if args[:2] == ["uvx", "edge-tts"]:
            raise FileNotFoundError("uvx")
        return FakeCompleted(0)

    runs = _patch_common(monkeypatch, runner)
    edge_speak.main()
    assert runs[-1][:3] == ["say", "-v", "Krzysztof"]
    assert "dzień dobry" in runs[-1]


def test_falls_back_to_say_on_timeout(monkeypatch):
    def runner(args, **kw):
        if args[:2] == ["uvx", "edge-tts"]:
            raise edge_speak.subprocess.TimeoutExpired(cmd="edge-tts", timeout=30)
        return FakeCompleted(0)

    runs = _patch_common(monkeypatch, runner)
    edge_speak.main()
    assert runs[-1][0] == "say"


def test_falls_back_to_say_on_nonzero_synth(monkeypatch):
    runs = _patch_common(monkeypatch, lambda args, **kw: FakeCompleted(1))
    edge_speak.main()
    assert runs[-1][0] == "say"  # synthesis failed → no afplay, say instead
    assert not any(r[0] == "afplay" for r in runs)


def test_no_payload_is_silent(monkeypatch):
    monkeypatch.delenv("SIMPLE_TTS_PAYLOAD", raising=False)
    ran = []
    monkeypatch.setattr(edge_speak.subprocess, "run", lambda *a, **k: ran.append(a))
    edge_speak.main()
    assert ran == []
