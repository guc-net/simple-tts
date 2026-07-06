#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook — oznacza "Claude pracuje" dla nakładki KITT.

Ustawia stan busy (tryb "think" nakładki). Czyszczony przez Stop hook.
Cichy no-op, gdy plugin nie jest skonfigurowany. Nic nie wypisuje na stdout,
więc nie dokłada kontekstu do promptu.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import load_config, set_busy


def main():
    if load_config() is None:
        sys.exit(0)
    set_busy(True)
    sys.exit(0)


if __name__ == '__main__':
    main()
