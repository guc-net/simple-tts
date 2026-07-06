"""Shared fixtures: import hooks/ modules and isolate all file paths
so tests never touch the user's real ~/.claude files."""

import json
import os
import sys

import pytest

HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import tts_utils  # noqa: E402


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect config, state and user-phonetics paths into tmp_path."""
    monkeypatch.setattr(tts_utils, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(tts_utils, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(tts_utils, "BUSY_DIR", str(tmp_path / "busy.d"))
    monkeypatch.setattr(tts_utils, "USER_PHONETICS_PATH", str(tmp_path / "phonetics.json"))
    return tmp_path


@pytest.fixture
def write_config(isolated_paths):
    """Write a plugin config into the isolated location and return its path."""

    def _write(**overrides):
        config = {"voice": "Krzysztof", "rate": 220, "language": "Polish",
                  "name": "", "name_chance": 0.0}
        config.update(overrides)
        path = isolated_paths / "config.json"
        path.write_text(json.dumps(config))
        return path

    return _write


class FakeProc:
    def __init__(self, pid=12345):
        self.pid = pid


class CallList(list):
    """A list of argv lists (so existing `==`/`[]`/`len` assertions keep
    working) that also records the `env` kwarg of each Popen call alongside,
    in `.envs`, for the edge-tts payload assertions."""

    envs = None


@pytest.fixture
def fake_say(monkeypatch):
    """Replace subprocess.Popen inside tts_utils with a recorder.
    Returns the list of argv lists passed to Popen; `.envs[i]` holds the
    `env` kwarg of call i (None when not passed)."""
    calls = CallList()
    calls.envs = []

    def fake_popen(args, **kwargs):
        calls.append(args)
        calls.envs.append(kwargs.get("env"))
        return FakeProc()

    monkeypatch.setattr(tts_utils.subprocess, "Popen", fake_popen)
    return calls
