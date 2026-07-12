"""Tests for the Stop hook: tag extraction from the message string."""

import pytest
import stop_tts
from stop_tts import extract_tts_from_message


class TestExtractFromMessage:
    def test_extracts_tag(self):
        msg = "Zrobione.\n\n<!-- TTS: naprawiłem parser -->"
        assert extract_tts_from_message(msg) == "naprawiłem parser"

    def test_tolerates_whitespace_variants(self):
        assert extract_tts_from_message("<!--TTS:   gotowe  -->") == "gotowe"

    def test_no_tag_returns_none(self):
        assert extract_tts_from_message("No tag here") is None

    def test_empty_or_none_returns_none(self):
        assert extract_tts_from_message("") is None
        assert extract_tts_from_message(None) is None

    def test_polish_diacritics_preserved(self):
        msg = "<!-- TTS: skończyłem migrację bazy -->"
        assert extract_tts_from_message(msg) == "skończyłem migrację bazy"


def test_hook_passes_project_from_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(stop_tts, "read_hook_input", lambda: {
        "session_id": "sX", "last_assistant_message": "<!-- TTS: gotowe -->",
        "cwd": "/Users/x/src/moj-projekt"})
    monkeypatch.setattr(stop_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        stop_tts.main()
    assert spoken[0][1].get("project") == "moj-projekt"


def test_hook_passes_project_none_without_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(stop_tts, "read_hook_input", lambda: {
        "session_id": "sX", "last_assistant_message": "<!-- TTS: gotowe -->"})
    monkeypatch.setattr(stop_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        stop_tts.main()
    assert spoken[0][1].get("project") is None
