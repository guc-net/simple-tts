#!/usr/bin/env python3
"""Claude Code SessionEnd hook — sprząta znaczniki tej sesji przy jej zamknięciu.

Bez tego zamknięta sesja zostawiała „osierocone" znaczniki: busy (nakładka dalej
pokazywałaby pracę) i attention (soczewki dalej świeciłyby na niebiesko „ktoś
czeka"), aż zestarzeją się po limicie czasu. Zdejmujemy oba od razu na czystym
wyjściu (zamknięte okno / /exit); twarde ubicie procesu dalej łapie limit staled.

Cichy no-op, gdy plugin nie jest skonfigurowany.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    load_config,
    read_hook_input,
    set_session_attention,
    set_session_busy,
)


def main():
    if load_config() is None:
        sys.exit(0)
    session_id = read_hook_input().get("session_id")
    set_session_busy(session_id, False)
    set_session_attention(session_id, False)
    sys.exit(0)


if __name__ == '__main__':
    main()
