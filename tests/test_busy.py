"""Testy znacznika 'busy' per-sesja (tryb 'think' nakładki)."""

import io
import os
import sys

import pytest

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import tts_utils  # noqa: E402


def test_set_session_busy_creates_and_removes(isolated_paths):
    tts_utils.set_session_busy("abc", True)
    assert (isolated_paths / "busy.d" / "abc").exists()
    tts_utils.set_session_busy("abc", False)
    assert not (isolated_paths / "busy.d" / "abc").exists()


def test_sessions_are_independent(isolated_paths):
    tts_utils.set_session_busy("a", True)
    tts_utils.set_session_busy("b", True)
    tts_utils.set_session_busy("a", False)
    assert not (isolated_paths / "busy.d" / "a").exists()
    assert (isolated_paths / "busy.d" / "b").exists()   # druga sesja dalej pracuje


def test_session_id_is_sanitized(isolated_paths):
    tts_utils.set_session_busy("../../evil id", True)
    files = list((isolated_paths / "busy.d").iterdir())
    assert len(files) == 1
    assert "/" not in files[0].name


def test_user_prompt_hook_sets_busy(write_config, isolated_paths, monkeypatch):
    write_config()
    import user_prompt
    monkeypatch.setattr(user_prompt, "read_hook_input",
                        lambda: {"session_id": "sess1"})
    with pytest.raises(SystemExit):
        user_prompt.main()
    assert (isolated_paths / "busy.d" / "sess1").exists()


def test_user_prompt_hook_noop_without_config(isolated_paths, monkeypatch):
    import user_prompt
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "x"}'))
    with pytest.raises(SystemExit):
        user_prompt.main()
    assert not (isolated_paths / "busy.d").exists()
