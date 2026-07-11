"""Testy znacznika 'busy' per-sesja (tryb 'think' nakładki)."""

import io
import os
import sys
import time

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


# --- znacznik 'attention' (sesja czeka na zgodę) ------------------------------

def test_set_session_attention_creates_and_removes(isolated_paths):
    tts_utils.set_session_attention("abc", True)
    assert (isolated_paths / "attention.d" / "abc").exists()
    tts_utils.set_session_attention("abc", False)
    assert not (isolated_paths / "attention.d" / "abc").exists()


def test_notification_hook_sets_attention(write_config, isolated_paths, monkeypatch):
    write_config()
    import notification_tts
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "s9",
        "message": "Claude needs your permission to use Bash"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert (isolated_paths / "attention.d" / "s9").exists()


def test_user_prompt_hook_clears_attention(write_config, isolated_paths, monkeypatch):
    write_config()
    tts_utils.set_session_attention("sess1", True)
    import user_prompt
    monkeypatch.setattr(user_prompt, "read_hook_input",
                        lambda: {"session_id": "sess1"})
    with pytest.raises(SystemExit):
        user_prompt.main()
    assert not (isolated_paths / "attention.d" / "sess1").exists()
    assert (isolated_paths / "busy.d" / "sess1").exists()


def test_stop_hook_clears_attention_and_busy(write_config, isolated_paths, monkeypatch):
    write_config()
    tts_utils.set_session_busy("sess2", True)
    tts_utils.set_session_attention("sess2", True)
    import stop_tts
    monkeypatch.setattr(stop_tts, "read_hook_input",
                        lambda: {"session_id": "sess2", "last_assistant_message": ""})
    monkeypatch.setattr(stop_tts, "speak", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        stop_tts.main()
    assert not (isolated_paths / "attention.d" / "sess2").exists()
    assert not (isolated_paths / "busy.d" / "sess2").exists()


def test_session_end_hook_clears_attention_and_busy(write_config, isolated_paths,
                                                    monkeypatch):
    """Zamknięcie sesji -> SessionEnd sprząta oba znaczniki (bez osieroceń)."""
    write_config()
    tts_utils.set_session_busy("sessE", True)
    tts_utils.set_session_attention("sessE", True)
    import session_end
    monkeypatch.setattr(session_end, "read_hook_input",
                        lambda: {"session_id": "sessE"})
    with pytest.raises(SystemExit):
        session_end.main()
    assert not (isolated_paths / "attention.d" / "sessE").exists()
    assert not (isolated_paths / "busy.d" / "sessE").exists()


def test_session_end_hook_noop_without_config(isolated_paths, monkeypatch):
    import session_end
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "x"}'))
    with pytest.raises(SystemExit):
        session_end.main()
    assert not (isolated_paths / "attention.d").exists()


def test_post_tool_use_hook_clears_attention(write_config, isolated_paths, monkeypatch):
    """Zgoda udzielona -> narzędzie się wykonało -> PostToolUse zdejmuje znacznik."""
    write_config()
    tts_utils.set_session_attention("sess3", True)
    import attention_clear
    monkeypatch.setattr(attention_clear, "read_hook_input",
                        lambda: {"session_id": "sess3"})
    with pytest.raises(SystemExit):
        attention_clear.main()
    assert not (isolated_paths / "attention.d" / "sess3").exists()


def test_post_tool_use_hook_fast_path_skips_stdin(isolated_paths, monkeypatch):
    """Brak znaczników -> hook wychodzi bez czytania stdin (zero kosztu na
    każdym wywołaniu narzędzia)."""
    import attention_clear

    def _boom():
        raise AssertionError("stdin nie powinien być czytany")

    monkeypatch.setattr(attention_clear, "read_hook_input", _boom)
    with pytest.raises(SystemExit):
        attention_clear.main()


def test_session_busy_fresh_true_when_recent(isolated_paths):
    tts_utils.set_session_busy("s1", True)
    assert tts_utils.session_busy_fresh("s1") is True


def test_session_busy_fresh_false_when_absent(isolated_paths):
    assert tts_utils.session_busy_fresh("nope") is False


def test_session_busy_fresh_false_when_stale(isolated_paths):
    tts_utils.set_session_busy("s2", True)
    marker = isolated_paths / "busy.d" / "s2"
    marker.write_text(str(int(time.time()) - 20 * 60))   # znacznik sprzed 20 min
    assert tts_utils.session_busy_fresh("s2") is False


def test_session_busy_fresh_none_session_is_false(isolated_paths):
    assert tts_utils.session_busy_fresh(None) is False


def test_notification_suppressed_when_busy(write_config, isolated_paths, monkeypatch):
    """Bezczynne 'waiting' w trakcie trwającej tury (świeży busy) -> cisza,
    bez zapalania attention."""
    write_config()
    tts_utils.set_session_busy("sB", True)
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sB", "message": "Claude is waiting for your input"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke == []
    assert not (isolated_paths / "attention.d" / "sB").exists()


def test_notification_permission_speaks_even_when_busy(write_config, isolated_paths, monkeypatch):
    """Prośba o zgodę mówi zawsze, nawet w trakcie trwającej tury."""
    write_config()
    tts_utils.set_session_busy("sP", True)
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sP", "message": "Claude needs your permission to use Bash"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke                                            # coś powiedziano
    assert (isolated_paths / "attention.d" / "sP").exists()


def test_notification_speaks_when_not_busy(write_config, isolated_paths, monkeypatch):
    """Realne bezczynne czekanie (brak busy = tura się skończyła) -> mówi."""
    write_config()
    import notification_tts
    spoke = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sN", "message": "Claude is waiting for your input"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoke
    assert (isolated_paths / "attention.d" / "sN").exists()
