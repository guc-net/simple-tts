#!/usr/bin/env python3
"""Shared TTS utilities for Claude Code simple-tts plugin (usterk/simple-tts)"""

import fcntl
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime

# Config file location
CONFIG_PATH = os.path.expanduser("~/.claude/simple-tts-config.json")
STATE_PATH = os.path.expanduser("~/.claude/simple-tts-state.json")
USER_PHONETICS_PATH = os.path.expanduser("~/.claude/simple-tts-phonetics.json")
PHONETICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phonetics")

DEFAULT_CONFIG = {
    "voice": "Krzysztof",
    "rate": 220,
    "language": "Polish",
    "name": "",
    "name_chance": 0.3,
}

# Map of language names (as stored by the setup skill) to phonetic dict codes
LANGUAGE_CODES = {
    "polish": "pl",
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
}


def load_config():
    """Load plugin config. Returns None when the plugin is not configured —
    callers must stay silent in that case (plugin enabled but setup not run)."""
    try:
        with open(CONFIG_PATH) as f:
            stored = json.load(f)
        return {**DEFAULT_CONFIG, **stored}
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def language_code(config):
    """Resolve the configured language to a two-letter code."""
    lang = str(config.get('language', 'Polish')).strip().lower()
    if len(lang) == 2:
        return lang
    return LANGUAGE_CODES.get(lang, 'en')


def extract_tts_from_transcript(transcript_path, search_lines=50):
    """
    Extract <!-- TTS: message --> tag from the last assistant message in transcript.
    """
    try:
        transcript_path = os.path.expanduser(transcript_path)
        with open(transcript_path) as f:
            lines = f.readlines()

        for line in reversed(lines[-search_lines:]):
            try:
                entry = json.loads(line)
                if entry.get('type') == 'assistant':
                    content = entry.get('message', {}).get('content', [])
                    if isinstance(content, list):
                        for block in content:
                            if block.get('type') == 'text':
                                match = re.search(
                                    r'<!--\s*TTS:\s*(.+?)\s*-->', block.get('text', '')
                                )
                                if match:
                                    return match.group(1).strip()
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None
    except Exception as e:
        print(f"Error reading transcript: {e}", file=sys.stderr)
        return None


def load_phonetics(lang_code):
    """Load the built-in phonetic dict for a language, merged with the
    user's overrides from ~/.claude/simple-tts-phonetics.json (user wins)."""
    phonetic = {}
    builtin = os.path.join(PHONETICS_DIR, f"{lang_code}.json")
    for path in (builtin, USER_PHONETICS_PATH):
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                phonetic.update(data)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return phonetic


def sanitize_for_tts(text, lang_code='pl'):
    """
    Make text pronounceable by a non-English TTS voice.
    - Phonetic replacements (whole words only, longest match first)
    - ALL-CAPS words (2+ letters) get spelled out: "API" -> "A P I"
    """
    phonetic = load_phonetics(lang_code)
    if phonetic:
        # Single alternation, longest keys first, so 'deployed' wins over 'deploy'
        keys = sorted(phonetic.keys(), key=len, reverse=True)
        pattern = r'\b(?:' + '|'.join(re.escape(k) for k in keys) + r')\b'
        lookup = {k.lower(): v for k, v in phonetic.items()}
        text = re.sub(pattern, lambda m: lookup[m.group(0).lower()], text,
                      flags=re.IGNORECASE)

    # Spell out ALL-CAPS words (2+ letters)
    def spell_caps(m):
        return ' '.join(m.group(0))
    text = re.sub(r'\b[A-Z]{2,}\b', spell_caps, text)

    return text


def in_quiet_hours(config, now=None):
    """True when the current time falls inside the configured quiet hours
    ({"quiet_hours": {"start": "22:00", "end": "07:00"}}). Windows may wrap
    past midnight. Missing, malformed or zero-length windows mean no quiet
    hours — speech stays on (fail-open by design)."""
    window = config.get('quiet_hours')
    if not isinstance(window, dict):
        return False
    try:
        start = datetime.strptime(str(window['start']), '%H:%M').time()
        end = datetime.strptime(str(window['end']), '%H:%M').time()
    except (KeyError, ValueError):
        return False
    if start == end:
        return False
    current = (now or datetime.now()).time().replace(second=0, microsecond=0)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _locked_state(fn):
    """Run fn(state) -> new_state under an exclusive flock on the state file.
    Returns the state fn saw. State is {"pid": int, "ts": float} or {}."""
    with open(STATE_PATH, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            state = json.load(f)
        except (json.JSONDecodeError, ValueError):
            state = {}
        new_state = fn(state)
        if new_state is not None:
            f.seek(0)
            f.truncate()
            json.dump(new_state, f)
        return state


def _is_our_say(pid):
    """True if pid is alive and is a `say` process (so we never kill
    someone else's process after PID reuse)."""
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    try:
        out = subprocess.run(['ps', '-p', str(pid), '-o', 'comm='],
                             capture_output=True, text=True)
        return out.stdout.strip().endswith('say')
    except OSError:
        return False


def speak(text, priority=False, force=False):
    """
    Speak text using macOS say with the configured voice. Non-blocking:
    `say` is detached and the hook returns immediately.

    priority=True (notification hook): kills our running say (if any), always speaks.
    priority=False (stop hook): stays silent while a previous say is still
    playing or finished less than 2 seconds ago.
    force=True (speak_cli test mode): bypasses mute ("enabled": false)
    and quiet hours, but still requires a config.

    Silent no-op when the plugin is not configured, muted, or in quiet hours.
    """
    config = load_config()
    if config is None:
        return
    if not force and (not config.get('enabled', True) or in_quiet_hours(config)):
        return

    def check_and_kill(state):
        pid, ts = state.get('pid'), state.get('ts', 0)
        if priority:
            if pid and _is_our_say(pid):
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            return None
        # Non-priority: bail out if still speaking or just finished
        if (pid and _is_our_say(pid)) or (time.time() - ts) < 2.0:
            raise _StillSpeaking()
        return None

    try:
        _locked_state(check_and_kill)
    except _StillSpeaking:
        return

    text = sanitize_for_tts(text, language_code(config))

    name = config.get('name', '')
    if name and random.random() < config.get('name_chance', 0.3):
        if not text.lower().startswith(name.lower()):
            text = f"{name}, {text[0].lower() + text[1:]}" if len(text) > 1 else f"{name}, {text}"

    voice = config.get('voice', 'Krzysztof')
    rate = str(config.get('rate', 220))

    try:
        proc = subprocess.Popen(['say', '-v', voice, '-r', rate, text],
                                start_new_session=True)
        _locked_state(lambda state: {"pid": proc.pid, "ts": time.time()})
    except (OSError, FileNotFoundError) as e:
        print(f"TTS error: {e}", file=sys.stderr)


class _StillSpeaking(Exception):
    pass


def read_hook_input():
    """Read and parse JSON input from stdin."""
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)
