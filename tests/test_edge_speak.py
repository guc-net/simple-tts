"""Tests for edge_speak.py — the detached edge-tts helper: it plays the
synthesized mp3 on success, caches it by content checksum (so a repeated phrase
skips synthesis), and falls back to local `say` on any failure."""

import json
import os

import edge_speak


class FakeCompleted:
    def __init__(self, returncode=0):
        self.returncode = returncode


def _payload(**overrides):
    p = {"edge_voice": "pl-PL-MarekNeural", "edge_rate": "+0%",
         "text": "dzień dobry", "say_voice": "Krzysztof", "say_rate": "220"}
    p.update(overrides)
    return p


def _synth_ok(args, **kw):
    """Fake `uvx edge-tts` that actually writes bytes to --write-media."""
    if args[:2] == ["uvx", "edge-tts"]:
        out = args[args.index("--write-media") + 1]
        with open(out, "wb") as f:
            f.write(b"ID3fake-audio")
    return FakeCompleted(0)


def _patch_common(monkeypatch, tmp_path, runner):
    """Wire env payload, a recording subprocess.run, and an isolated cache dir."""
    runs = []

    def fake_run(args, **kwargs):
        runs.append(args)
        return runner(args, **kwargs)

    monkeypatch.setattr(edge_speak, "CACHE_DIR", str(tmp_path / "audiocache"))
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD", json.dumps(_payload()))
    monkeypatch.setattr(edge_speak.subprocess, "run", fake_run)
    return runs


def test_synthesizes_then_plays(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    edge_speak.main()
    assert runs[0][:2] == ["uvx", "edge-tts"]
    assert "pl-PL-MarekNeural" in runs[0]
    assert runs[1][0] == "afplay"  # plays the result, no say fallback


def test_stores_in_cache_by_checksum(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, _synth_ok)
    edge_speak.main()
    cache_path = edge_speak._cache_path(_payload())
    assert os.path.exists(cache_path)  # named by sha256 of voice+rate+text
    assert os.path.getsize(cache_path) > 0


def test_cache_hit_skips_synthesis(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    cache_path = edge_speak._cache_path(_payload())
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(b"cached-audio")

    edge_speak.main()

    assert not any(r[:2] == ["uvx", "edge-tts"] for r in runs)  # no synth
    assert runs[0] == ["afplay", cache_path]  # plays straight from cache


def test_second_identical_call_uses_cache(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    edge_speak.main()
    edge_speak.main()
    synth_calls = [r for r in runs if r[:2] == ["uvx", "edge-tts"]]
    assert len(synth_calls) == 1  # synthesized once, replayed from cache


def test_different_voice_is_a_separate_cache_entry(monkeypatch, tmp_path):
    assert (edge_speak._cache_path(_payload(edge_voice="pl-PL-MarekNeural"))
            != edge_speak._cache_path(_payload(edge_voice="pl-PL-ZofiaNeural")))


def test_falls_back_to_say_when_uvx_missing(monkeypatch, tmp_path):
    def runner(args, **kw):
        if args[:2] == ["uvx", "edge-tts"]:
            raise FileNotFoundError("uvx")
        return FakeCompleted(0)

    runs = _patch_common(monkeypatch, tmp_path, runner)
    edge_speak.main()
    assert runs[-1][:3] == ["say", "-v", "Krzysztof"]
    assert "dzień dobry" in runs[-1]


def test_falls_back_to_say_on_timeout(monkeypatch, tmp_path):
    def runner(args, **kw):
        if args[:2] == ["uvx", "edge-tts"]:
            raise edge_speak.subprocess.TimeoutExpired(cmd="edge-tts", timeout=30)
        return FakeCompleted(0)

    runs = _patch_common(monkeypatch, tmp_path, runner)
    edge_speak.main()
    assert runs[-1][0] == "say"


def test_falls_back_to_say_on_nonzero_synth(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, lambda args, **kw: FakeCompleted(1))
    edge_speak.main()
    assert runs[-1][0] == "say"  # synthesis failed → no afplay, say instead
    assert not any(r[0] == "afplay" for r in runs)


def test_failed_synth_leaves_no_temp_file(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, lambda args, **kw: FakeCompleted(1))
    edge_speak.main()
    leftovers = [n for n in os.listdir(edge_speak.CACHE_DIR)
                 if n.startswith(edge_speak.TMP_PREFIX)]
    assert leftovers == []  # temp cleaned up in finally


def test_no_payload_is_silent(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLE_TTS_PAYLOAD", raising=False)
    ran = []
    monkeypatch.setattr(edge_speak.subprocess, "run", lambda *a, **k: ran.append(a))
    edge_speak.main()
    assert ran == []
