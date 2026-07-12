"""Testy hooka PreToolUse czytającego treść realnego pytania decyzyjnego."""

import io
import os
import sys

import pytest

HOOKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
sys.path.insert(0, HOOKS_DIR)

import ask_question_tts  # noqa: E402


class TestBuildPhrase:
    def setup_method(self):
        self.p = ask_question_tts.PHRASES['pl']

    def test_single_question(self):
        ti = {"questions": [{"question": "Której biblioteki użyć?"}]}
        assert ask_question_tts.build_phrase("AskUserQuestion", ti, self.p) == \
            "Której biblioteki użyć?"

    def test_several_questions_reads_first(self):
        ti = {"questions": [{"question": "Pierwsze pytanie?"},
                            {"question": "Drugie pytanie?"}]}
        out = ask_question_tts.build_phrase("AskUserQuestion", ti, self.p)
        assert out == "Mam kilka pytań, pierwsze: Pierwsze pytanie?"

    def test_exit_plan_mode(self):
        assert ask_question_tts.build_phrase("ExitPlanMode", {}, self.p) == \
            "Plan gotowy, zatwierdzić?"

    def test_empty_questions_returns_none(self):
        assert ask_question_tts.build_phrase(
            "AskUserQuestion", {"questions": []}, self.p) is None

    def test_other_tool_returns_none(self):
        assert ask_question_tts.build_phrase("Bash", {"command": "ls"}, self.p) is None

    def test_long_question_truncated(self):
        ti = {"questions": [{"question": "słowo " * 60}]}
        out = ask_question_tts.build_phrase("AskUserQuestion", ti, self.p)
        assert len(out) <= ask_question_tts.MAX_LEN + 1     # +1 na znak …
        assert out.endswith("…")

    def test_several_phrase_bounded_to_max_len(self):
        ti = {"questions": [{"question": "słowo " * 60}, {"question": "drugie?"}]}
        out = ask_question_tts.build_phrase("AskUserQuestion", ti, self.p)
        assert len(out) <= ask_question_tts.MAX_LEN + 1
        assert out.endswith("…")

    def test_non_string_question_value_returns_none(self):
        assert ask_question_tts.build_phrase(
            "AskUserQuestion", {"questions": [{"question": None}]}, self.p) is None
        assert ask_question_tts.build_phrase(
            "AskUserQuestion", {"questions": [{"question": 5}]}, self.p) is None

    def test_mixed_valid_and_non_string_questions_keeps_valid(self):
        ti = {"questions": [{"question": None}, {"question": "Realne pytanie?"}]}
        assert ask_question_tts.build_phrase("AskUserQuestion", ti, self.p) == \
            "Realne pytanie?"


def test_all_phrase_catalogs_have_same_keys():
    for lang in ("pl", "en", "de", "fr"):
        assert set(ask_question_tts.PHRASES[lang]) == set(ask_question_tts.PHRASES["en"])


def test_hook_speaks_and_sets_attention(write_config, isolated_paths, monkeypatch):
    write_config()
    spoke = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q1", "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Czy wdrażamy?"}]}})
    monkeypatch.setattr(ask_question_tts, "speak",
                        lambda text, **k: spoke.append((text, k)))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoke and "Czy wdrażamy?" in spoke[0][0]
    assert spoke[0][1].get("priority") is True
    assert (isolated_paths / "attention.d" / "q1").exists()


def test_hook_noop_without_config(isolated_paths, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "AskUserQuestion"}'))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert not (isolated_paths / "attention.d").exists()


def test_hook_noop_for_other_tool(write_config, isolated_paths, monkeypatch):
    write_config()
    spoke = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q2", "tool_name": "Bash", "tool_input": {"command": "ls"}})
    monkeypatch.setattr(ask_question_tts, "speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoke == []
    assert not (isolated_paths / "attention.d" / "q2").exists()


def test_hook_passes_project_from_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q3", "tool_name": "ExitPlanMode",
        "cwd": "/Users/x/src/moj-projekt"})
    monkeypatch.setattr(ask_question_tts, "speak",
                        lambda text, **k: spoken.append((text, k)))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoken[0][1].get("project") == "moj-projekt"


def test_hook_passes_project_none_without_cwd(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(ask_question_tts, "read_hook_input", lambda: {
        "session_id": "q4", "tool_name": "ExitPlanMode"})
    monkeypatch.setattr(ask_question_tts, "speak",
                        lambda text, **k: spoken.append((text, k)))
    with pytest.raises(SystemExit):
        ask_question_tts.main()
    assert spoken[0][1].get("project") is None
