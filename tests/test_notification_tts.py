"""Tests for the Notification hook: tool extraction and message translation."""

import notification_tts
import pytest
from notification_tts import MESSAGES, extract_tool, translate_notification


class TestExtractTool:
    def test_extracts_tool_name(self):
        msg = "Claude needs your permission to use Bash"
        assert extract_tool(msg) == "Bash"

    def test_extracts_with_run_verb(self):
        msg = "Claude needs your permission to run git push"
        assert extract_tool(msg) == "git push"

    def test_strips_trailing_period(self):
        msg = "Claude needs your permission to use WebFetch."
        assert extract_tool(msg) == "WebFetch"

    def test_no_tool_returns_none(self):
        assert extract_tool("Claude is waiting for your input") is None


class TestTranslateNotification:
    def test_permission_with_tool_pl(self):
        result = translate_notification(
            "Claude needs your permission to use Bash", MESSAGES["pl"])
        assert result == "Potrzebuję zgody na narzędzie Bash"

    def test_permission_without_tool(self):
        result = translate_notification(
            "Claude requested permission", MESSAGES["pl"])
        assert result == "Potrzebuję zgody"

    def test_waiting(self):
        result = translate_notification(
            "Claude is waiting for your input", MESSAGES["en"])
        assert result == "Waiting for your reply"

    def test_error(self):
        result = translate_notification("Command failed", MESSAGES["de"])
        assert result == "Es gab ein Problem"

    def test_empty_message_falls_back_to_attention(self):
        result = translate_notification("", MESSAGES["pl"])
        assert result == "Potrzebuję Twojej uwagi"

    def test_unknown_message_falls_back_to_attention(self):
        result = translate_notification("Something unusual happened here",
                                        MESSAGES["fr"])
        assert result == "J'ai besoin de ton attention"

    @pytest.mark.parametrize("lang", ["pl", "en", "de", "fr"])
    def test_all_catalogs_have_same_keys(self, lang):
        assert set(MESSAGES[lang]) == set(MESSAGES["en"])


def test_hook_passes_project_from_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sY", "message": "Claude needs your permission to use Bash",
        "cwd": "/Users/x/src/moj-projekt"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoken[0][1].get("project") == "moj-projekt"


def test_hook_passes_project_none_without_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sY", "message": "Claude needs your permission to use Bash"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoken[0][1].get("project") is None


def test_hook_passes_session_id(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(notification_tts, "read_hook_input", lambda: {
        "session_id": "sY", "message": "Claude needs your permission to use Bash"})
    monkeypatch.setattr(notification_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        notification_tts.main()
    assert spoken[0][1].get("session_id") == "sY"
