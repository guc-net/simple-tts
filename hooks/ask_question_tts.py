#!/usr/bin/env python3
"""Claude Code PreToolUse hook (AskUserQuestion / ExitPlanMode): wypowiada treść
realnego pytania decyzyjnego od razu, gdy agent je zadaje — zamiast czekać na
bezczynne "waiting" po ~60 s. Ustawia też znacznik 'attention' nakładki. Cichy
no-op bez configu i dla innych narzędzi (matcher w hooks.json zawęża, ale hook
broni się też sam)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    language_code,
    load_config,
    read_hook_input,
    set_session_attention,
    speak,
)

MAX_LEN = 140

PHRASES = {
    'pl': {'plan': "Plan gotowy, zatwierdzić?",
           'several': "Mam kilka pytań, pierwsze: {q}"},
    'en': {'plan': "Plan ready, approve it?",
           'several': "I have a few questions, first: {q}"},
    'de': {'plan': "Plan fertig, genehmigen?",
           'several': "Ich habe mehrere Fragen, erste: {q}"},
    'fr': {'plan': "Plan prêt, approuver ?",
           'several': "J'ai plusieurs questions, la première : {q}"},
}


def _truncate(text, limit=MAX_LEN):
    """Zbij whitespace i przytnij na granicy słowa, dokładając '…'."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def build_phrase(tool_name, tool_input, phrases):
    """Fraza do wypowiedzenia albo None, gdy nie ma czego mówić."""
    if tool_name == "ExitPlanMode":
        return phrases['plan']
    if tool_name == "AskUserQuestion":
        questions = (tool_input or {}).get("questions") or []
        texts = [q.get("question", "").strip() for q in questions
                 if isinstance(q, dict) and q.get("question", "").strip()]
        if not texts:
            return None
        if len(texts) == 1:
            return _truncate(texts[0])
        return phrases['several'].format(q=_truncate(texts[0]))
    return None


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()
    phrases = PHRASES.get(language_code(config), PHRASES['en'])
    text = build_phrase(input_data.get("tool_name", ""),
                        input_data.get("tool_input", {}), phrases)
    if not text:
        sys.exit(0)

    # Realne pytanie -> sesja czeka na użytkownika (tryb attention nakładki).
    set_session_attention(input_data.get("session_id"), True)
    speak(text, priority=True)   # speak() sam sanitizuje tekst
    sys.exit(0)


if __name__ == '__main__':
    main()
