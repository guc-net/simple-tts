"""Tests for edge_speak.py — the detached edge-tts helper: it plays the
synthesized mp3 on success, caches it by content checksum (so a repeated phrase
skips synthesis), and falls back to local `say` on any failure."""

import json
import os
import time

import audio_cache as ac
import edge_speak
import tts_utils as tu


class FakeCompleted:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


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

    monkeypatch.setattr(ac, "CACHE_DIR", str(tmp_path / "audiocache"))
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
    cache_file = ac.cache_path(_payload())
    assert os.path.exists(cache_file)  # named by sha256 of voice+rate+text
    assert os.path.getsize(cache_file) > 0
    # metadata recorded with a play count
    assert ac.stats()["entries"][0]["plays"] == 1


def test_cache_hit_skips_synthesis(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    cache_file = ac.cache_path(_payload())
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "wb") as f:
        f.write(b"cached-audio")

    edge_speak.main()

    assert not any(r[:2] == ["uvx", "edge-tts"] for r in runs)  # no synth
    assert runs[0] == ["afplay", cache_file]  # plays straight from cache


def test_second_identical_call_uses_cache_and_counts_plays(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    edge_speak.main()
    edge_speak.main()
    synth_calls = [r for r in runs if r[:2] == ["uvx", "edge-tts"]]
    assert len(synth_calls) == 1  # synthesized once, replayed from cache
    assert ac.stats()["entries"][0]["plays"] == 2  # both uses counted


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
    leftovers = [n for n in os.listdir(ac.CACHE_DIR)
                 if n.startswith(ac.TMP_PREFIX)]
    assert leftovers == []  # temp cleaned up in finally


def _synth_and_mix(args, **kw):
    """Fake pipeline: uvx synth writes bytes, ffprobe reports a duration,
    ffmpeg writes the mixed output, afplay/say succeed."""
    if args[:2] == ["uvx", "edge-tts"]:
        with open(args[args.index("--write-media") + 1], "wb") as f:
            f.write(b"ID3fake-audio")
        return FakeCompleted(0)
    if args[0] == "ffprobe":
        return FakeCompleted(0, stdout="3.0\n")
    if args[0] == "ffmpeg":
        with open(args[-1], "wb") as f:  # last arg is the mixed output path
            f.write(b"ID3mixed-audio")
        return FakeCompleted(0)
    return FakeCompleted(0)


def test_intro_sound_mixes_kitt_and_plays_the_mix(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_speak.shutil, "which", lambda _: "/usr/bin/x")
    runs = _patch_common(monkeypatch, tmp_path, _synth_and_mix)
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD",
                       json.dumps(_payload(intro_sound="kitt")))
    edge_speak.main()

    assert any(r[0] == "ffmpeg" for r in runs)  # a mix happened
    afplay = next(r for r in runs if r[0] == "afplay")
    assert "simple-tts-kitt-" in afplay[1]  # played the mixed temp, not raw speech
    # cache still holds the PLAIN speech (mix is playback-only)
    with open(ac.cache_path(_payload()), "rb") as f:
        assert f.read() == b"ID3fake-audio"


def test_mix_failure_falls_back_to_plain_speech(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_speak.shutil, "which", lambda _: "/usr/bin/x")

    def runner(args, **kw):
        if args[0] == "ffmpeg":
            return FakeCompleted(1)  # mixing fails
        return _synth_and_mix(args, **kw)

    runs = _patch_common(monkeypatch, tmp_path, runner)
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD",
                       json.dumps(_payload(intro_sound="kitt")))
    edge_speak.main()

    afplay = next(r for r in runs if r[0] == "afplay")
    assert afplay[1] == ac.cache_path(_payload())  # plain speech, no say fallback


def test_intro_sound_none_skips_mixing(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_speak.shutil, "which", lambda _: "/usr/bin/x")
    runs = _patch_common(monkeypatch, tmp_path, _synth_and_mix)
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD",
                       json.dumps(_payload(intro_sound="none")))
    edge_speak.main()
    assert not any(r[0] in ("ffmpeg", "ffprobe") for r in runs)


def test_no_payload_is_silent(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLE_TTS_PAYLOAD", raising=False)
    ran = []
    monkeypatch.setattr(edge_speak.subprocess, "run", lambda *a, **k: ran.append(a))
    edge_speak.main()
    assert ran == []


# --- _speak_payload: engine='say' bypasses cache/synthesis entirely --------

def test_speak_payload_say_engine_calls_say_and_skips_uvx(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(edge_speak, "_say", lambda p: calls.append(p))

    def fail_run(args, **kw):
        raise AssertionError(f"subprocess.run should not run for engine=say: {args}")

    monkeypatch.setattr(edge_speak.subprocess, "run", fail_run)
    monkeypatch.setattr(ac, "CACHE_DIR", str(tmp_path / "audiocache"))

    payload = _payload(engine="say")
    edge_speak._speak_payload(payload)

    assert calls == [payload]


# --- _speak_payload: engine='edge' (or missing) behaves like the old main() -

def test_speak_payload_edge_engine_cache_hit(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)
    cache_file = ac.cache_path(_payload())
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "wb") as f:
        f.write(b"cached-audio")

    edge_speak._speak_payload(_payload(engine="edge"))

    assert not any(r[:2] == ["uvx", "edge-tts"] for r in runs)
    assert runs[0] == ["afplay", cache_file]


def test_speak_payload_missing_engine_key_defaults_to_edge_and_synthesizes(monkeypatch, tmp_path):
    runs = _patch_common(monkeypatch, tmp_path, _synth_ok)

    edge_speak._speak_payload(_payload())  # no "engine" key at all

    assert runs[0][:2] == ["uvx", "edge-tts"]
    assert runs[1][0] == "afplay"


# --- main(): thin wrapper around _speak_payload + _drain_loop --------------

def test_main_calls_speak_payload_then_drain_loop(monkeypatch):
    order = []
    payload = _payload()
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD", json.dumps(payload))
    monkeypatch.setattr(edge_speak, "_speak_payload", lambda p: order.append(("speak", p)))
    monkeypatch.setattr(edge_speak, "_drain_loop", lambda: order.append(("drain",)))

    edge_speak.main()

    assert order == [("speak", payload), ("drain",)]


def test_main_no_payload_does_not_speak_or_drain(monkeypatch):
    monkeypatch.delenv("SIMPLE_TTS_PAYLOAD", raising=False)
    calls = []
    monkeypatch.setattr(edge_speak, "_speak_payload", lambda p: calls.append(p))
    monkeypatch.setattr(edge_speak, "_drain_loop", lambda: calls.append("drain"))

    edge_speak.main()

    assert calls == []


def test_main_empty_text_does_not_speak_or_drain(monkeypatch):
    monkeypatch.setenv("SIMPLE_TTS_PAYLOAD", json.dumps({"text": ""}))
    calls = []
    monkeypatch.setattr(edge_speak, "_speak_payload", lambda p: calls.append(p))
    monkeypatch.setattr(edge_speak, "_drain_loop", lambda: calls.append("drain"))

    edge_speak.main()

    assert calls == []


# --- _drain_step -------------------------------------------------------

def test_drain_step_pops_next_payload_and_refreshes_state(isolated_paths):
    tu._locked_state(lambda s: {"pid": os.getpid(), "ts": 1.0})
    tu._queue_enqueue({"text": "kolejny"})

    result = edge_speak._drain_step()

    assert result == {"payload": {"text": "kolejny"}}
    state = tu._locked_state(lambda s: None)
    assert state["pid"] == os.getpid()
    assert state["ts"] > 1.0
    assert list((isolated_paths / "queue.d").iterdir()) == []


def test_drain_step_stops_and_clears_pid_when_queue_empty(isolated_paths):
    tu._locked_state(lambda s: {"pid": os.getpid(), "ts": 1.0})

    result = edge_speak._drain_step()

    assert result == {"stop": True}
    state = tu._locked_state(lambda s: None)
    assert "pid" not in state
    assert state["ts"] > 1.0


def test_drain_step_stops_without_touching_state_when_pid_mismatched(isolated_paths):
    tu._locked_state(lambda s: {"pid": 999999, "ts": 1.0})
    tu._queue_enqueue({"text": "nietknięty"})
    queue_dir = isolated_paths / "queue.d"
    before = sorted(os.listdir(queue_dir))

    result = edge_speak._drain_step()

    assert result == {"stop": True}
    state = tu._locked_state(lambda s: None)
    assert state == {"pid": 999999, "ts": 1.0}
    assert sorted(os.listdir(queue_dir)) == before
    assert len(before) == 1


def test_drain_step_stops_without_touching_state_when_state_empty(isolated_paths):
    result = edge_speak._drain_step()

    assert result == {"stop": True}
    state = tu._locked_state(lambda s: None)
    assert state == {}


# --- _drain_loop ---------------------------------------------------------

def test_drain_loop_speaks_all_queued_entries_in_fifo_order_then_stops(isolated_paths, monkeypatch):
    monkeypatch.setattr(edge_speak.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(edge_speak, "_speak_payload", lambda p: calls.append(p))

    tu._locked_state(lambda s: {"pid": os.getpid(), "ts": time.time()})
    tu._queue_enqueue({"text": "pierwszy"})
    time.sleep(0.001)  # different time_ns() prefix, keeps FIFO order deterministic
    tu._queue_enqueue({"text": "drugi"})

    edge_speak._drain_loop()

    assert calls == [{"text": "pierwszy"}, {"text": "drugi"}]
    assert list((isolated_paths / "queue.d").iterdir()) == []  # drained, no leftovers
    state = tu._locked_state(lambda s: None)
    assert "pid" not in state  # loop left the idle state behind, not our own pid
