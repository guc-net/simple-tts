#!/usr/bin/env python3
"""Claude Code PostToolUse hook — heartbeat 'busy' + clear 'attention'.

Fires on EVERY tool call — of the main agent AND of its subagents (subagents
run their own PostToolUse hooks). Two jobs:

1. Heartbeat: refresh this session's 'busy' marker so the overlay's 'think'
   mode stays alive as long as tools keep running. Without this the marker is
   only stamped once at UserPromptSubmit and cleared at Stop, so a session that
   hands work to subagents (or a background job re-invoked between turns) drops
   to 'idle' while it's still working — the tool boundary is the reliable
   "still working" signal that survives sub-turn Stop/UserPromptSubmit churn.
2. Clear attention: a tool ran, so any pending permission was granted — the
   session is no longer waiting on the user.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import read_hook_input, set_session_attention, set_session_busy


def main():
    session_id = read_hook_input().get("session_id")
    set_session_busy(session_id, True)        # heartbeat -> keep 'think' alive
    set_session_attention(session_id, False)  # tool ran -> not waiting anymore
    sys.exit(0)


if __name__ == '__main__':
    main()
