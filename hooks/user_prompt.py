#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — oznacza "ta sesja pracuje" dla nakładki KITT.

Ustawia znacznik busy per-sesja (tryb "think"). Zdejmowany przez Stop hook.
Cichy no-op, gdy plugin nie jest skonfigurowany. Nic nie wypisuje na stdout,
więc nie dokłada kontekstu do promptu.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import load_config, read_hook_input, set_session_busy


def main():
    if load_config() is None:
        sys.exit(0)
    session_id = read_hook_input().get("session_id")
    set_session_busy(session_id, True)
    sys.exit(0)


if __name__ == '__main__':
    main()
