#!/usr/bin/env python3
"""
Claude Code Stop Hook - Speaks contextual TTS summary when Claude finishes.
Reads <!-- TTS: message --> from last_assistant_message or transcript.
Only speaks if a TTS tag is found — stays silent when Claude stops
for permission prompts (notification hook handles those).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    extract_tts_from_transcript,
    load_config,
    parse_tts_tag,
    read_hook_input,
    set_session_attention,
    set_session_busy,
    speak,
)


def extract_tts_from_message(message):
    """Extract (category, text) TTS tag directly from the last assistant
    message string, or None when there's no tag."""
    if not message:
        return None
    return parse_tts_tag(message)


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()

    # Claude skończył pracę -> ta sesja wychodzi z trybu "think" (chyba że
    # zaraz zacznie mówić: tryb "speak" ma pierwszeństwo w kitt_state).
    # Zdejmujemy też ewentualny znacznik "attention" — tura się skończyła.
    set_session_busy(input_data.get('session_id'), False)
    set_session_attention(input_data.get('session_id'), False)

    # In "tool" mode the model speaks via the speak MCP tool, so the Stop hook
    # has nothing to do (and must stay silent to avoid double speech).
    if config.get('speak_via', 'tag') == 'tool':
        sys.exit(0)

    if input_data.get('stop_hook_active'):
        sys.exit(0)

    # Strategy 1: Try last_assistant_message (fastest)
    result = extract_tts_from_message(input_data.get('last_assistant_message', ''))

    # Strategy 2: Fall back to transcript parsing
    if not result:
        transcript_path = input_data.get('transcript_path')
        if transcript_path:
            result = extract_tts_from_transcript(transcript_path)

    if result:
        category, tts_text = result
    else:
        # No tag found: Claude likely stopped for a permission prompt (the
        # notification hook handles those), so default to silence — unless
        # the user configured a fallback message ("fallback_message" in
        # config).
        category = None
        tts_text = config.get('fallback_message')

    if tts_text:
        speak(tts_text, project=os.path.basename(input_data.get('cwd') or '') or None,
              category=category)

    sys.exit(0)


if __name__ == '__main__':
    main()
