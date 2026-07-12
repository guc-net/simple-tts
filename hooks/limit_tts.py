#!/usr/bin/env python3
"""Claude Code StopFailure hook — speaks a short alert when the turn ends due
to an API error (rate limit, plan/usage limit, output-token cap, overload).

StopFailure fires INSTEAD of Stop when the turn is cut short by an API error;
its matcher selects on error type (rate_limit, billing_error, max_output_tokens,
overloaded, …). We speak with priority=True so the alert interrupts whatever is
playing. Silent no-op without config, like every other hook. The exact input
schema for StopFailure is undocumented, so we read error_type defensively and
fall back to a generic phrase when it's missing/unrecognized.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from tts_utils import (
    language_code,
    load_config,
    read_hook_input,
    speak,
)

MESSAGES = {
    'pl': {
        'rate_limit': "Osiągnięto limit zapytań, poczekaj chwilę",
        'billing_error': "Wyczerpano limit planu",
        'max_output_tokens': "Przekroczono limit długości odpowiedzi",
        'overloaded': "Serwery są przeciążone",
        'limit': "Osiągnięto limit sesji",
    },
    'en': {
        'rate_limit': "Rate limit reached, wait a moment",
        'billing_error': "Plan usage limit reached",
        'max_output_tokens': "Response length limit exceeded",
        'overloaded': "Servers are overloaded",
        'limit': "Session limit reached",
    },
    'de': {
        'rate_limit': "Anfragelimit erreicht, warte einen Moment",
        'billing_error': "Nutzungslimit des Plans erreicht",
        'max_output_tokens': "Längenlimit der Antwort überschritten",
        'overloaded': "Server sind überlastet",
        'limit': "Sitzungslimit erreicht",
    },
    'fr': {
        'rate_limit': "Limite de requêtes atteinte, patiente un instant",
        'billing_error': "Limite d'utilisation du forfait atteinte",
        'max_output_tokens': "Limite de longueur de réponse dépassée",
        'overloaded': "Les serveurs sont surchargés",
        'limit': "Limite de session atteinte",
    },
}


def translate_limit(error_type, msgs):
    """Map an API error type to a short spoken phrase, falling back to the
    generic 'limit' phrase for an empty/unrecognized type."""
    return msgs.get(error_type) or msgs['limit']


def main():
    config = load_config()
    if config is None:
        sys.exit(0)

    input_data = read_hook_input()
    session_id = input_data.get('session_id')
    error_type = input_data.get('error_type', '')

    msgs = MESSAGES.get(language_code(config), MESSAGES['en'])
    tts_text = translate_limit(error_type, msgs)

    speak(tts_text, priority=True,
          project=os.path.basename(input_data.get('cwd') or '') or None,
          session_id=session_id)
    sys.exit(0)


if __name__ == '__main__':
    main()
