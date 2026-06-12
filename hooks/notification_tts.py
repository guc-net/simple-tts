#!/usr/bin/env python3
"""
Claude Code Notification Hook - Speaks short message when user attention is needed.
Always uses the notification message directly (not transcript TTS tag,
which belongs to the previous response, not the current permission request).
Spoken phrases follow the configured language; permission requests mention
the tool involved when the notification message names one.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import language_code, load_config, read_hook_input, speak

DEBUG_LOG = os.path.expanduser("~/.claude/simple-tts-notification-debug.log")
DEBUG_MAX_LINES = 200

MESSAGES = {
    'pl': {
        'permission': "Potrzebuję zgody",
        'permission_tool': "Potrzebuję zgody na narzędzie {tool}",
        'waiting': "Czekam na odpowiedź",
        'error': "Wystąpił problem",
        'attention': "Potrzebuję Twojej uwagi",
    },
    'en': {
        'permission': "I need your permission",
        'permission_tool': "I need permission to use {tool}",
        'waiting': "Waiting for your reply",
        'error': "Something went wrong",
        'attention': "I need your attention",
    },
    'de': {
        'permission': "Ich brauche deine Genehmigung",
        'permission_tool': "Ich brauche Genehmigung für {tool}",
        'waiting': "Ich warte auf deine Antwort",
        'error': "Es gab ein Problem",
        'attention': "Ich brauche deine Aufmerksamkeit",
    },
    'fr': {
        'permission': "J'ai besoin de ton accord",
        'permission_tool': "J'ai besoin d'accord pour {tool}",
        'waiting': "J'attends ta réponse",
        'error': "Un problème est survenu",
        'attention': "J'ai besoin de ton attention",
    },
}


def debug(input_data, enabled):
    """Opt-in debug log (config "debug": true), trimmed to the last
    DEBUG_MAX_LINES entries so it never grows unbounded."""
    if not enabled:
        return
    try:
        try:
            with open(DEBUG_LOG) as f:
                lines = f.readlines()[-(DEBUG_MAX_LINES - 1):]
        except FileNotFoundError:
            lines = []
        lines.append(json.dumps(input_data, default=str, ensure_ascii=False)[:500] + "\n")
        with open(DEBUG_LOG, 'w') as f:
            f.writelines(lines)
    except OSError:
        pass


def extract_tool(message):
    """Pull the tool/command name out of messages like
    'Claude needs your permission to use Bash'."""
    match = re.search(r'permission to (?:use|run) (.+?)(?:\.|$)', message, re.IGNORECASE)
    return match.group(1).strip() if match else None


def translate_notification(message, msgs):
    """Produce a short spoken notification in the configured language."""
    if not message:
        return msgs['attention']

    msg = message.lower()
    if 'permission' in msg:
        tool = extract_tool(message)
        if tool:
            return msgs['permission_tool'].format(tool=tool)
        return msgs['permission']
    if 'waiting' in msg or 'input' in msg:
        return msgs['waiting']
    if 'error' in msg or 'failed' in msg:
        return msgs['error']
    return msgs['attention']


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()
    debug(input_data, config.get('debug', False))

    msgs = MESSAGES.get(language_code(config), MESSAGES['en'])
    tts_text = translate_notification(input_data.get('message', ''), msgs)
    speak(tts_text, priority=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
