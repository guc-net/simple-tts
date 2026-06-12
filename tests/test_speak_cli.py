"""Tests for the speak_cli test-mode entry point."""

import pytest
import speak_cli


class TestSpeakCli:
    def test_speaks_joined_args_with_force(self, write_config, monkeypatch):
        write_config(enabled=False)  # CLI must speak even when muted
        calls = []
        monkeypatch.setattr(speak_cli, "speak",
                            lambda text, **kw: calls.append((text, kw)))
        speak_cli.main(["dzień", "dobry"])
        assert len(calls) == 1
        text, kwargs = calls[0]
        assert text == "dzień dobry"
        assert kwargs.get("force") is True

    def test_no_args_exits_with_usage(self, capsys):
        with pytest.raises(SystemExit) as exc:
            speak_cli.main([])
        assert exc.value.code != 0
        assert "usage" in capsys.readouterr().err.lower()

    def test_unconfigured_exits_with_error(self, isolated_paths, capsys):
        with pytest.raises(SystemExit) as exc:
            speak_cli.main(["tekst"])
        assert exc.value.code != 0
        assert "config" in capsys.readouterr().err.lower()
