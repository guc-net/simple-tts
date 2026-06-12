#!/usr/bin/env python3
"""Test-mode CLI for the simple-tts plugin: speaks the given text through
the full pipeline (config voice/rate, phonetic sanitizer), bypassing mute
and quiet hours. For checking configuration and pronunciations by hand:

    python3 hooks/speak_cli.py "deployed do produkcji"
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import load_config, speak


def main(argv):
    if not argv:
        print(f"usage: {os.path.basename(__file__)} <text to speak>", file=sys.stderr)
        sys.exit(2)
    if load_config() is None:
        print("simple-tts is not configured — run /simple-tts-setup first "
              "(missing ~/.claude/simple-tts-config.json)", file=sys.stderr)
        sys.exit(1)
    speak(' '.join(argv), force=True)


if __name__ == '__main__':
    main(sys.argv[1:])
