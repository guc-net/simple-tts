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
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    load_config,
    set_session_attention,
    set_session_busy,
    voice_gender,
)

# The `speak` tool's fully-qualified name depends on how the MCP server was
# loaded. Marketplace plugin install namespaces it under the plugin; a
# project-scoped `.mcp.json` load (working inside the repo) does not.
SPEAK_TOOL = "mcp__plugin_simple-tts_simple-tts__speak"      # plugin install
SPEAK_TOOL_PROJECT = "mcp__simple-tts__speak"                # project .mcp.json

EXAMPLES = {
    'Polish': {
        'male': '"Poprawiłem parser zgodnie z wytycznymi", "Znalazłem błąd w module autoryzacji", '
                '"Testy przechodzą, mogę zatwierdzić?", "Potrzebuję zgody na migrację"',
        'female': '"Poprawiłam parser zgodnie z wytycznymi", '
                  '"Znalazłam błąd w module autoryzacji", '
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
        " spoken-language summary — short enough to hear in a few seconds,"
        " specific enough to be useful.",
    ]
    lines += content_rules(config)
    lines.append("  - In this environment use ONLY the TTS tag — never call the simple-tts"
                 " `speak` MCP tool here (the tag is spoken automatically; the tool is for"
                 " environments without hooks and would cause double speech)")
    return '\n'.join(lines)


def build_tool_instruction(config):
    lines = [
        "- At the END of each response, speak a short summary aloud to the user by calling"
        " the simple-tts `speak` tool (the `speak` tool from MCP server `simple-tts`)."
        " Call it once, as your final action, when:",
        "  1. Completing a task — say what you did",
        "  2. Before user interaction — say what you need or found, and set priority=true"
        " so it interrupts",
        "  - The user may be away from the screen; this spoken summary is how they know"
        " what happened or that you need them.",
        "  - The tool's full name depends on how it was loaded: it appears as either"
        f" `{SPEAK_TOOL}` (plugin install) or `{SPEAK_TOOL_PROJECT}` (project load)."
        " Use whichever one is actually present — do not assume one.",
        "  - If `speak` appears as a deferred tool, load it first with ToolSearch using a"
        " keyword query (\"simple-tts speak\") so it matches whichever name is registered,"
        " then call that exact name. It stays loaded for the rest of the session.",
        "  - Do NOT write any `<!-- TTS: ... -->` tag or put this summary in your visible reply —"
        " the tool speaks it, and a visible marker is exactly what we are avoiding here.",
        "  - Write your complete answer to the user as ONE block of text — never split it"
        " across several messages or restate it. Each separate chunk of prose shows as its"
        " own bubble in the CLI, so one answer must be one bubble.",
        "  - The `speak` call is your final action and carries NO accompanying prose: do not"
        " greet, summarise, or repeat any of your answer in the same turn as the call —"
        " just make the call.",
        "  - If you must run ToolSearch to load `speak`, do it silently — emit no text in that"
        " turn (ToolSearch, then the `speak` call), so it does not add an extra bubble.",
    ]
    lines += content_rules(config)
    return '\n'.join(lines)


def build_instruction(config):
    if config.get('speak_via', 'tag') == 'tool':
        return build_tool_instruction(config)
    return build_tag_instruction(config)


def _clear_session_markers():
    """Nowy start sesji (startup / resume / /clear) — sesja nie czeka na usera
    ani nie pracuje. Zdejmij jej znaczniki attention i busy, żeby overlay nie
    wisiał na kolorze uwagi po wyczyszczeniu rozmowy. Odczyt stdin tylko gdy to
    realny hook (nie terminal), żeby ręczne uruchomienie się nie blokowało."""
    if sys.stdin.isatty():
        return
    try:
        session_id = (json.load(sys.stdin) or {}).get("session_id")
    except Exception:
        return
    if not session_id:
        return
    try:
        set_session_attention(session_id, False)
        set_session_busy(session_id, False)
    except Exception:
        pass


def main():
    config = load_config()
    if config is None:
        # Plugin enabled but not configured — inject nothing
        sys.exit(0)

    _clear_session_markers()
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_instruction(config),
        }
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
