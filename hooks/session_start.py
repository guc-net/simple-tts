#!/usr/bin/env python3
"""
Claude Code SessionStart Hook - Injects the TTS-tag instruction into context.
Generated dynamically from the user's config (language, voice gender, name),
so it always matches the current configuration. Replaces the old approach of
appending a static block to the user's CLAUDE.md.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import load_config

MALE_VOICES = {'krzysztof', 'daniel', 'thomas', 'alex', 'jorge', 'luca'}
FEMALE_VOICES = {'ewa', 'zosia', 'samantha', 'anna', 'amélie', 'monica'}

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


def voice_gender(voice):
    first = voice.strip().split()[0].lower() if voice.strip() else ''
    if first in FEMALE_VOICES:
        return 'female'
    return 'male'


def build_instruction(config):
    language = config.get('language', 'Polish')
    gender = voice_gender(config.get('voice', ''))

    lang_examples = EXAMPLES.get(language, EXAMPLES['English'])
    examples = lang_examples.get(gender) or lang_examples.get('any') \
        or next(iter(lang_examples.values()))

    lines = [
        f"- Add `<!-- TTS: short message in {language} -->` tag at the end of your response when:",
        "  1. Completing a task (what you did in context of user's request)",
        "  2. Before user interaction (what you need or found)",
        "  - This tag is read aloud to the user via macOS TTS so they can switch console"
        " knowing the gist of your response without reading it. It must be a natural,"
        " spoken-language summary — short enough to hear in a few seconds, specific"
        " enough to be useful.",
        f"  - Max 10 words, in {language}, contextual to the user's last message",
        f"  - Examples: {examples}",
        "  - NEVER generic — always relate to what was actually done or needed",
    ]

    gender_rule = GENDER_RULES.get(language, {}).get(gender)
    if gender_rule:
        lines.append(f"  - {gender_rule}")

    lines += [
        "  - In this environment use ONLY the TTS tag — never call the simple-tts"
        " `speak` MCP tool here (the tag is spoken automatically; the tool is for"
        " environments without hooks and would cause double speech)",
        "  - TTS voice may mispronounce foreign words. Rules:",
        f"    - Prefer {language} descriptions over English acronyms or jargon",
        "    - If a technical name MUST appear, use phonetic spelling readable by the TTS voice",
        "    - NEVER put acronyms (API, GOPATH, JSON, URL) in the TTS tag"
        " — describe what they are instead",
    ]
    return '\n'.join(lines)


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
