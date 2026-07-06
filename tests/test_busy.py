"""Testy stanu 'busy' (tryb 'think' nakładki): set_busy + hooki."""

import os
import sys

import pytest

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import tts_utils  # noqa: E402


def test_set_busy_writes_flag(isolated_paths):
    tts_utils.set_busy(True)
    assert (isolated_paths / "busy").read_text() == "1"
    tts_utils.set_busy(False)
    assert (isolated_paths / "busy").read_text() == "0"


def test_user_prompt_hook_sets_busy(write_config, isolated_paths):
    write_config()                       # plugin skonfigurowany
    import user_prompt
    with pytest.raises(SystemExit):
        user_prompt.main()
    assert (isolated_paths / "busy").read_text() == "1"


def test_user_prompt_hook_noop_without_config(isolated_paths):
    import user_prompt
    with pytest.raises(SystemExit):
        user_prompt.main()               # brak configu -> cichy no-op
    assert not (isolated_paths / "busy").exists()
