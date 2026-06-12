#!/usr/bin/env python3
"""
Claude Code SessionStart Hook - Injects the TTS instruction into context.
Generated dynamically from the user's config (language, voice gender, name,
delivery mechanism), so it always matches the current configuration.

Two delivery mechanisms (config "speak_via"):
  - "tag"  (default): Claude appends a hidden `<!-- TTS: ... -->` comment; the
    Stop hook reads and speaks it. Zero latency, but the comment is visible in
    CLI versions that render HTML comments.
  - "tool": Claude calls the simple-tts `speak` MCP tool instead. Nothing shows
    in the prose (only a collapsed tool-use line); costs one extra model turn.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import load_config

MALE_VOICES = {'krzysztof', 'daniel', 'thomas', 'alex', 'jorge', 'luca'}
FEMALE_VOICES = {'ewa', 'zosia', 'samantha', 'anna', 'amélie', 'monica'}

SPEAK_TOOL = "mcp__plugin_simple-tts_simple-tts__speak"

EXAMPLES = {
    'Polish': {
        'male': '"Poprawiłem parser zgodnie z wytycznymi", "Znalazłem błąd w module autoryzacji", '
                '"Testy przechodzą, mogę zatwierdzić?", "Potrzebuję zgody na migrację"',
        'female': '"Poprawiłam parser zgodnie z wytycznymi", "Znalazłam błąd w module autoryzacji", '
                  '"Testy przechodzą, mogę zatwierdzić?", "Potrzebuję zgody na migrację"',
    },
    'English': {
        'any': '"Fixed the parser as requested", "Found a bug in auth module", '
               '"Tests pass, can I commit?", "Need your approval to run migration"',
    },
    'German': {
        'any': '"Parser wie gewünscht korrigiert", "Fehler im Auth-Modul gefunden", '
               '"Tests bestanden, soll ich committen?", "Brauche Genehmigung für Migration"',
    },
    'French': {
        'any': '"Parseur corrigé comme demandé", "Bug trouvé dans le module auth", '
               '"Tests réussis, je commit?", "Besoin d\'approbation pour la migration"',
    },
}

GENDER_RULES = {
    'Polish': {
        'male': 'TTS voice is male — use masculine verb forms (zrobiłem, znalazłem, naprawiłem)',
        'female': 'TTS voice is female — use feminine verb forms (zrobiłam, znalazłam, naprawiłam)',
    },
    'German': {
        'male': 'TTS voice is male — use masculine forms where applicable',
        'female': 'TTS voice is female — use feminine forms where applicable',
    },
}


def voice_gender(voice):
    first = voice.strip().split()[0].lower() if voice.strip() else ''
    if first in FEMALE_VOICES:
        return 'female'
    return 'male'


def content_rules(config):
    """The shared 'what to say' rules — independent of delivery mechanism."""
    language = config.get('language', 'Polish')
    gender = voice_gender(config.get('voice', ''))

    lang_examples = EXAMPLES.get(language, EXAMPLES['English'])
    examples = lang_examples.get(gender) or lang_examples.get('any') \
        or next(iter(lang_examples.values()))

    lines = [
        f"  - Max 10 words, in {language}, contextual to the user's last message",
        f"  - Examples: {examples}",
        "  - NEVER generic — always relate to what was actually done or needed",
    ]
    gender_rule = GENDER_RULES.get(language, {}).get(gender)
    if gender_rule:
        lines.append(f"  - {gender_rule}")
    lines += [
        "  - TTS voice may mispronounce foreign words. Rules:",
        f"    - Prefer {language} descriptions over English acronyms or jargon",
        "    - If a technical name MUST appear, use phonetic spelling readable by the TTS voice",
        "    - NEVER put acronyms (API, GOPATH, JSON, URL) in it — describe what they are instead",
    ]
    return lines


def build_tag_instruction(config):
    language = config.get('language', 'Polish')
    lines = [
        f"- Add `<!-- TTS: short message in {language} -->` tag at the end of your response when:",
        "  1. Completing a task (what you did in context of user's request)",
        "  2. Before user interaction (what you need or found)",
        "  - This tag is read aloud to the user via macOS TTS so they can switch console"
        " knowing the gist of your response without reading it. It must be a natural,"
        " spoken-language summary — short enough to hear in a few seconds, specific enough to be useful.",
    ]
    lines += content_rules(config)
    lines.append("  - In this environment use ONLY the TTS tag — never call the simple-tts"
                 " `speak` MCP tool here (the tag is spoken automatically; the tool is for"
                 " environments without hooks and would cause double speech)")
    return '\n'.join(lines)


def build_tool_instruction(config):
    lines = [
        f"- At the END of each response, speak a short summary aloud to the user by calling"
        f" the simple-tts `speak` tool (MCP server `simple-tts`, tool name `{SPEAK_TOOL}`)."
        " Call it once, as your final action, when:",
        "  1. Completing a task — say what you did",
        "  2. Before user interaction — say what you need or found, and set priority=true so it interrupts",
        "  - The user may be away from the screen; this spoken summary is how they know"
        " what happened or that you need them.",
        f"  - If `speak` appears as a deferred tool, load it first with ToolSearch"
        " (query: \"select:" + SPEAK_TOOL + "\"), then call it. It stays loaded for the rest of the session.",
        "  - Do NOT write any `<!-- TTS: ... -->` tag or put this summary in your visible reply —"
        " the tool speaks it, and a visible marker is exactly what we are avoiding here.",
    ]
    lines += content_rules(config)
    return '\n'.join(lines)


def build_instruction(config):
    if config.get('speak_via', 'tag') == 'tool':
        return build_tool_instruction(config)
    return build_tag_instruction(config)


def main():
    config = load_config()
    if config is None:
        # Plugin enabled but not configured — inject nothing
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_instruction(config),
        }
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
