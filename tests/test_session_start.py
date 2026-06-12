"""Tests for the SessionStart hook: gender detection and instruction text."""

from session_start import build_instruction, voice_gender


class TestVoiceGender:
    def test_female_voice(self):
        assert voice_gender("Ewa") == "female"

    def test_female_voice_with_quality_suffix(self):
        assert voice_gender("Ewa (Premium)") == "female"

    def test_male_voice(self):
        assert voice_gender("Krzysztof") == "male"

    def test_unknown_defaults_to_male(self):
        assert voice_gender("Zaphod") == "male"

    def test_empty_defaults_to_male(self):
        assert voice_gender("") == "male"


class TestBuildInstruction:
    def test_polish_male_grammar(self):
        text = build_instruction({"language": "Polish", "voice": "Krzysztof"})
        assert "zrobiłem" in text
        assert "Polish" in text

    def test_polish_female_grammar(self):
        text = build_instruction({"language": "Polish", "voice": "Ewa"})
        assert "zrobiłam" in text

    def test_unknown_language_falls_back_to_english_examples(self):
        text = build_instruction({"language": "Esperanto", "voice": "Alex"})
        assert "Fixed the parser" in text
        assert "Esperanto" in text

    def test_mentions_mcp_tool_prohibition(self):
        text = build_instruction({"language": "English", "voice": "Daniel"})
        assert "speak" in text and "MCP" in text
