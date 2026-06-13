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

    def test_default_is_tag_mode(self):
        text = build_instruction({"language": "Polish", "voice": "Krzysztof"})
        assert "<!-- TTS:" in text


class TestToolMode:
    def _cfg(self, **kw):
        return {"language": "Polish", "voice": "Krzysztof", "speak_via": "tool", **kw}

    def test_tool_mode_calls_speak_tool(self):
        text = build_instruction(self._cfg())
        assert "mcp__plugin_simple-tts_simple-tts__speak" in text

    def test_tool_mode_mentions_project_scoped_name(self):
        # Working inside the repo, the server is loaded via project .mcp.json,
        # so the tool is NOT plugin-namespaced — the instruction must cover it.
        text = build_instruction(self._cfg())
        assert "mcp__simple-tts__speak" in text

    def test_tool_mode_uses_keyword_toolsearch(self):
        # A keyword query matches whichever name is registered; an exact
        # select: of the wrong name would silently fail to load the tool.
        text = build_instruction(self._cfg())
        assert "simple-tts speak" in text
        assert "select:mcp__" not in text

    def test_tool_mode_emits_no_tag(self):
        text = build_instruction(self._cfg())
        assert "<!-- TTS:" not in text or "Do NOT write any `<!-- TTS:" in text
        # the only mention of the tag must be the prohibition, never an instruction to emit it
        assert "Add `<!-- TTS:" not in text

    def test_tool_mode_keeps_content_rules(self):
        text = build_instruction(self._cfg())
        assert "Max 10 words" in text
        assert "zrobiłem" in text  # gender forms still applied

    def test_tool_mode_mentions_toolsearch(self):
        text = build_instruction(self._cfg())
        assert "ToolSearch" in text

    def test_tool_mode_demands_single_block_no_prose(self):
        # The instruction must forbid splitting the answer across messages and
        # forbid prose alongside the speak call — that was the multi-bubble bug.
        text = build_instruction(self._cfg())
        assert "ONE block" in text
        assert "NO accompanying prose" in text
        assert "silently" in text  # the ToolSearch step must not emit text
