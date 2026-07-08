#!/usr/bin/env python3
"""Claude Code PostToolUse hook — zdejmuje znacznik "attention" tej sesji.

Gdy narzędzie się wykonało, ewentualna zgoda została już udzielona, więc sesja
nie czeka na użytkownika. Hook odpala się przy KAŻDYM wywołaniu narzędzia,
dlatego ścieżka szybka (brak jakichkolwiek znaczników attention) wychodzi po
jednym listdir, zanim w ogóle dotknie stdin.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import tts_utils
from tts_utils import read_hook_input, set_session_attention


def _any_attention_marker():
    # tts_utils.ATTENTION_DIR dynamicznie (testy monkeypatchują atrybut modułu)
    try:
        return bool(os.listdir(tts_utils.ATTENTION_DIR))
    except OSError:
        return False


def main():
    if not _any_attention_marker():
        sys.exit(0)
    session_id = read_hook_input().get("session_id")
    set_session_attention(session_id, False)
    sys.exit(0)


if __name__ == '__main__':
    main()
