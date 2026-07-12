"""Tests for message_display.py — the MessageDisplay hook that rewrites the
hidden <!-- TTS: ... --> marker into what the console shows, while leaving the
transcript (which the Stop hook reads) untouched.

Modes (config key `tag_display`):
- styled (default): green 🔊 line
- plain:            🔊 line, no ANSI (fallback if a terminal mangles ANSI)
- hidden:           marker removed entirely

The hook is field-name-agnostic: Claude Code's MessageDisplay stdin schema is
undocumented, so it locates the marker anywhere in the JSON."""

import io
import json

import message_display as md


def _run(stdin_obj, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin_obj)))
    md.main()
    return capsys.readouterr().out


def test_styled_renders_green_speaker_line():
    out = md.render_tag("Zrobione.\n\n<!-- TTS: Gotowe, naprawiłem błąd -->\n", "styled")
    assert "🔊 Gotowe, naprawiłem błąd" in out
    assert md.GREEN in out and md.RESET in out
    assert "TTS:" not in out and "<!--" not in out
    assert "Zrobione." in out


def test_plain_has_speaker_without_ansi():
    out = md.render_tag("X\n<!-- TTS: cześć -->", "plain")
    assert "🔊 cześć" in out
    assert md.GREEN not in out


def test_hidden_removes_marker():
    assert md.render_tag("Zrobione.\n\n<!-- TTS: x -->\n", "hidden") == "Zrobione."


def test_multiline_marker_is_collapsed():
    out = md.render_tag("A\n<!-- TTS: wielo\n   liniowy -->\nB", "styled")
    assert "🔊 wielo liniowy" in out


def test_text_without_marker_unchanged():
    assert md.render_tag("Zwykła odpowiedź.", "styled") == "Zwykła odpowiedź."


def test_emits_displaycontent_when_marker_present(monkeypatch, capsys):
    out = _run({"message": "Cześć.\n\n<!-- TTS: Cześć, gotowy -->\n"}, monkeypatch, capsys)
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "MessageDisplay"
    assert "🔊 Cześć, gotowy" in payload["hookSpecificOutput"]["displayContent"]


def test_finds_marker_in_nested_field(monkeypatch, capsys):
    out = _run({"data": {"content": "X <!-- TTS: y -->"}}, monkeypatch, capsys)
    payload = json.loads(out)
    assert "🔊 y" in payload["hookSpecificOutput"]["displayContent"]


def test_no_marker_produces_no_output(monkeypatch, capsys):
    assert _run({"message": "Bez znacznika."}, monkeypatch, capsys).strip() == ""


def test_bad_json_is_silent(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    md.main()
    assert capsys.readouterr().out.strip() == ""


def test_category_ok_is_green():
    out = md.render_tag("<!-- TTS[ok]: gotowe -->", "styled")
    assert md.GREEN in out
    assert "🔊 gotowe" in out


def test_category_err_is_firebrick():
    out = md.render_tag("<!-- TTS[err]: boom -->", "styled")
    assert md.FIREBRICK in out
    assert "🔊 boom" in out
    assert md.GREEN not in out


def test_category_q_is_amber():
    out = md.render_tag("<!-- TTS[q]: która opcja? -->", "styled")
    assert md.AMBER in out


def test_no_category_still_green():
    out = md.render_tag("<!-- TTS: neutralnie -->", "styled")
    assert md.GREEN in out


def test_plain_ignores_category():
    out = md.render_tag("<!-- TTS[err]: x -->", "plain")
    assert out == "🔊 x"
    assert md.FIREBRICK not in out
    assert md.GREEN not in out


def test_hidden_removes_categorized_marker():
    assert md.render_tag("A\n<!-- TTS[q]: x -->\n", "hidden") == "A"


def test_unknown_category_not_rewritten():
    text = "<!-- TTS[foo]: x -->"
    assert md.render_tag(text, "styled") == text


def test_prefilter_finds_categorized_marker(monkeypatch, capsys):
    out = _run({"message": "tekst <!-- TTS[err]: boom -->"}, monkeypatch, capsys)
    payload = json.loads(out)
    display = payload["hookSpecificOutput"]["displayContent"]
    assert "🔊 boom" in display
    assert md.FIREBRICK in display
