"""Tests for the PostToolUse hook (attention_clear.py): it must both keep the
'busy' marker fresh (heartbeat, so 'think' doesn't die mid-turn while the agent
or its subagents keep running tools) and clear this session's 'attention'
marker (a tool ran, so any permission was granted)."""

import os

import attention_clear
import pytest
import tts_utils


def _attention_marker_exists(session_id):
    return os.path.exists(tts_utils._session_marker(tts_utils.ATTENTION_DIR, session_id))


def test_posttool_refreshes_busy_marker(isolated_paths, monkeypatch):
    # No attention markers anywhere: the hook must STILL heartbeat the busy
    # marker (this is the fix — a running tool means the session is working).
    monkeypatch.setattr(attention_clear, "read_hook_input", lambda: {"session_id": "sHB"})
    with pytest.raises(SystemExit):
        attention_clear.main()
    assert tts_utils.session_busy_fresh("sHB")


def test_posttool_clears_attention_and_heartbeats(isolated_paths, monkeypatch):
    tts_utils.set_session_attention("sHB", True)
    monkeypatch.setattr(attention_clear, "read_hook_input", lambda: {"session_id": "sHB"})
    with pytest.raises(SystemExit):
        attention_clear.main()
    assert tts_utils.session_busy_fresh("sHB")
    assert not _attention_marker_exists("sHB")


def test_posttool_heartbeat_does_not_touch_other_session(isolated_paths, monkeypatch):
    monkeypatch.setattr(attention_clear, "read_hook_input", lambda: {"session_id": "mine"})
    with pytest.raises(SystemExit):
        attention_clear.main()
    assert tts_utils.session_busy_fresh("mine")
    assert not tts_utils.session_busy_fresh("someone-else")
