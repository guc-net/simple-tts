"""Tests for the StopFailure hook: spoken alert when a turn ends on an API
limit/error (rate limit, plan/usage limit, output-token cap, overload)."""

import limit_tts
import pytest
from limit_tts import MESSAGES, translate_limit


class TestTranslateLimit:
    def test_rate_limit_pl(self):
        assert translate_limit("rate_limit", MESSAGES["pl"]) == \
            "Osiągnięto limit zapytań, poczekaj chwilę"

    def test_billing_error_pl(self):
        assert translate_limit("billing_error", MESSAGES["pl"]) == \
            "Wyczerpano limit planu"

    def test_max_output_tokens_pl(self):
        assert translate_limit("max_output_tokens", MESSAGES["pl"]) == \
            "Przekroczono limit długości odpowiedzi"

    def test_overloaded_pl(self):
        assert translate_limit("overloaded", MESSAGES["pl"]) == \
            "Serwery są przeciążone"

    def test_unknown_error_type_falls_back_to_generic(self):
        # docs don't guarantee error_type; an unmapped/empty value must still
        # produce a spoken alert, not crash or stay silent.
        assert translate_limit("something_new", MESSAGES["pl"]) == \
            MESSAGES["pl"]["limit"]

    def test_empty_error_type_falls_back_to_generic(self):
        assert translate_limit("", MESSAGES["en"]) == MESSAGES["en"]["limit"]

    @pytest.mark.parametrize("lang", ["pl", "en", "de", "fr"])
    def test_all_catalogs_have_same_keys(self, lang):
        assert set(MESSAGES[lang]) == set(MESSAGES["en"])


def test_hook_silent_without_config(monkeypatch, isolated_paths):
    # No config file written -> load_config() is None -> no speech, clean exit.
    spoken = []
    monkeypatch.setattr(limit_tts, "read_hook_input", lambda: {
        "session_id": "sX", "error_type": "rate_limit"})
    monkeypatch.setattr(limit_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        limit_tts.main()
    assert spoken == []


def test_hook_speaks_priority_with_project_and_session(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(limit_tts, "read_hook_input", lambda: {
        "session_id": "sY", "error_type": "billing_error",
        "cwd": "/Users/x/src/moj-projekt"})
    monkeypatch.setattr(limit_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        limit_tts.main()
    assert len(spoken) == 1
    args, kwargs = spoken[0]
    assert args[0] == "Wyczerpano limit planu"
    assert kwargs.get("priority") is True
    assert kwargs.get("project") == "moj-projekt"
    assert kwargs.get("session_id") == "sY"


def test_hook_generic_when_error_type_absent(write_config, monkeypatch):
    write_config()
    spoken = []
    monkeypatch.setattr(limit_tts, "read_hook_input", lambda: {"session_id": "sZ"})
    monkeypatch.setattr(limit_tts, "speak", lambda *a, **k: spoken.append((a, k)))
    with pytest.raises(SystemExit):
        limit_tts.main()
    assert spoken[0][0][0] == MESSAGES["pl"]["limit"]
