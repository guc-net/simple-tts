#!/usr/bin/env python3
"""
Claude Code Stop Hook - Speaks contextual TTS summary when Claude finishes.
Reads <!-- TTS: message --> from last_assistant_message or transcript.
Only speaks if a TTS tag is found — stays silent when Claude stops
for permission prompts (notification hook handles those).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import extract_tts_from_transcript, load_config, read_hook_input, speak


def extract_tts_from_message(message):
    """Extract TTS tag directly from the last assistant message string."""
    if not message:
        return None
    match = re.search(r'<!--\s*TTS:\s*(.+?)\s*-->', message)
    return match.group(1).strip() if match else None


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()

    if input_data.get('stop_hook_active'):
        sys.exit(0)

    # Strategy 1: Try last_assistant_message (fastest)
    tts_text = extract_tts_from_message(input_data.get('last_assistant_message', ''))

    # Strategy 2: Fall back to transcript parsing
    if not tts_text:
        transcript_path = input_data.get('transcript_path')
        if transcript_path:
            tts_text = extract_tts_from_transcript(transcript_path)

    # No tag found: Claude likely stopped for a permission prompt (the
    # notification hook handles those), so default to silence — unless the
    # user configured a fallback message ("fallback_message" in config).
    if not tts_text:
        tts_text = config.get('fallback_message')

    if tts_text:
        speak(tts_text)

    sys.exit(0)


if __name__ == '__main__':
    main()
