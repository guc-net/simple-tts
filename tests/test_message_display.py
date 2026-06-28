"""Tests for message_display.py — the MessageDisplay hook that redacts the
hidden <!-- TTS: ... --> marker from what the console shows, while leaving the
transcript (which the Stop hook reads) untouched.

The hook is written field-name-agnostic: Claude Code's MessageDisplay stdin
schema is undocumented, so the hook locates the marker anywhere in the JSON and
returns the cleaned text via hookSpecificOutput.displayContent."""

import io
import json

import message_display as md


def _run(stdin_obj, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin_obj)))
    md.main()
    return capsys.readouterr().out


def test_strip_tag_removes_marker_and_trailing_blank():
    text = "Zrobione.\n\n<!-- TTS: Gotowe, naprawiłem błąd -->\n"
    assert md.strip_tag(text) == "Zrobione."


def test_strip_tag_leaves_text_without_marker_unchanged():
    text = "Zwykła odpowiedź bez znacznika."
    assert md.strip_tag(text) == text


def test_strip_tag_handles_inline_and_multiline_marker():
    text = "A\n<!--   TTS: wielo\nliniowy -->\nB"
    assert "TTS:" not in md.strip_tag(text)
    assert "A" in md.strip_tag(text) and "B" in md.strip_tag(text)


def test_emits_displaycontent_when_marker_present(monkeypatch, capsys):
    out = _run({"message": "Cześć.\n\n<!-- TTS: Cześć, gotowy -->\n"}, monkeypatch, capsys)
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "MessageDisplay"
    assert payload["hookSpecificOutput"]["displayContent"] == "Cześć."


def test_finds_marker_in_nested_field(monkeypatch, capsys):
    out = _run({"data": {"content": "X <!-- TTS: y -->"}}, monkeypatch, capsys)
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["displayContent"] == "X"


def test_no_marker_produces_no_output(monkeypatch, capsys):
    out = _run({"message": "Bez znacznika."}, monkeypatch, capsys)
    assert out.strip() == ""


def test_bad_json_is_silent(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    md.main()
    assert capsys.readouterr().out.strip() == ""
