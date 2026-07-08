#!/usr/bin/env python3
"""Shared TTS utilities for Claude Code simple-tts plugin (usterk/simple-tts)"""

import fcntl
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from datetime import datetime

# Config file location
CONFIG_PATH = os.path.expanduser("~/.claude/simple-tts-config.json")
STATE_PATH = os.path.expanduser("~/.claude/simple-tts-state.json")
# "Sesja pracuje" dla nakładki KITT: jeden plik-znacznik na sesję (touch od
# UserPromptSubmit, rm od Stop). Katalog, bo Claude może chodzić w kilku sesjach.
BUSY_DIR = os.path.expanduser("~/.claude/simple-tts-busy.d")
ATTENTION_DIR = os.path.expanduser("~/.claude/simple-tts-attention.d")
USER_PHONETICS_PATH = os.path.expanduser("~/.claude/simple-tts-phonetics.json")
PHONETICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phonetics")
EDGE_SPEAK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_speak.py")

DEFAULT_CONFIG = {
    "voice": "Krzysztof",
    "rate": 220,
    "language": "Polish",
    "name": "",
    "name_chance": 0.3,
    # Speech engine: "edge" = Microsoft edge-tts (online, neural, high quality),
    # falling back to macOS `say` on any failure; "say" = local `say` only.
    "engine": "edge",
    # edge-tts speed as a percentage offset from normal (e.g. "+0%", "-10%").
    "edge_rate": "+0%",
    # Total size budget (MB) for the on-disk edge-tts audio cache; least-used-
    # then-oldest entries are evicted once it is exceeded.
    "cache_max_mb": 100,
    # Background sound mixed under the speech (1 s intro + quiet-ducked bed +
    # outro ending in the sound's quiet valley). "kitt" = Knight Rider bed;
    # "none" (or "") = plain speech. Applies to the edge engine only. Only
    # used when knight_rider is on (below).
    "intro_sound": "kitt",
    # "Knight Rider" mode: the KITT siren bed under the voice + the floating
    # scanner overlay animation (idle / thinking / speaking). One switch for
    # both. Default on. When off: plain voice, no bed, no overlay.
    "knight_rider": True,
    # Overlay animation theme: kitt | cylon | hal | ekg | matrix | lava.
    # Unknown values fall back to "kitt". Switchable live (/tts theme <name>).
    "overlay_theme": "kitt",
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

# Voice first-names grouped by gender — used both to pick masculine/feminine
# grammar forms (session_start) and to choose the matching edge-tts voice.
MALE_VOICES = {'krzysztof', 'daniel', 'thomas', 'alex', 'jorge', 'luca'}
FEMALE_VOICES = {'ewa', 'zosia', 'samantha', 'anna', 'amélie', 'monica'}

# edge-tts neural voices per language code and gender. A language with no
# entry has no edge voice → speak() falls back to the local `say` engine.
EDGE_VOICES = {
    'pl': {'male': 'pl-PL-MarekNeural', 'female': 'pl-PL-ZofiaNeural'},
    'en': {'male': 'en-US-GuyNeural', 'female': 'en-US-AriaNeural'},
    'de': {'male': 'de-DE-ConradNeural', 'female': 'de-DE-KatjaNeural'},
    'fr': {'male': 'fr-FR-HenriNeural', 'female': 'fr-FR-DeniseNeural'},
    'es': {'male': 'es-ES-AlvaroNeural', 'female': 'es-ES-ElviraNeural'},
    'it': {'male': 'it-IT-DiegoNeural', 'female': 'it-IT-ElsaNeural'},
}


def voice_gender(voice):
    """Infer 'male'/'female' from a configured voice name (first word).
    Defaults to 'male' for unknown voices."""
    first = voice.strip().split()[0].lower() if voice.strip() else ''
    if first in FEMALE_VOICES:
        return 'female'
    return 'male'


def edge_voice_for(config):
    """Resolve the edge-tts voice for this config from language + voice gender,
    or None when the language has no edge mapping (caller uses `say` instead)."""
    lang = EDGE_VOICES.get(language_code(config))
    if not lang:
        return None
    return lang.get(voice_gender(config.get('voice', '')))


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


# Polish spoken-time tables (feminine ordinals for hours, feminine cardinals
# for minutes, matching how clock times are read aloud in Polish).
_PL_HOURS = {
    0: "północ", 1: "pierwsza", 2: "druga", 3: "trzecia", 4: "czwarta",
    5: "piąta", 6: "szósta", 7: "siódma", 8: "ósma", 9: "dziewiąta",
    10: "dziesiąta", 11: "jedenasta", 12: "dwunasta", 13: "trzynasta",
    14: "czternasta", 15: "piętnasta", 16: "szesnasta", 17: "siedemnasta",
    18: "osiemnasta", 19: "dziewiętnasta", 20: "dwudziesta",
    21: "dwudziesta pierwsza", 22: "dwudziesta druga", 23: "dwudziesta trzecia",
}
_PL_ONES = ["", "jedna", "dwie", "trzy", "cztery", "pięć", "sześć", "siedem",
            "osiem", "dziewięć"]
_PL_TEENS = ["dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście",
             "piętnaście", "szesnaście", "siedemnaście", "osiemnaście",
             "dziewiętnaście"]
_PL_TENS = {2: "dwadzieścia", 3: "trzydzieści", 4: "czterdzieści", 5: "pięćdziesiąt"}


def _pl_minutes(m):
    if m == 0:
        return ""
    if m < 10:
        return "zero " + _PL_ONES[m]
    if m < 20:
        return _PL_TEENS[m - 10]
    tens, ones = divmod(m, 10)
    return _PL_TENS[tens] + ("" if ones == 0 else " " + _PL_ONES[ones])


def normalize_times_pl(text):
    """Rewrite HH:MM clock times into spoken Polish words so macOS `say`
    doesn't expand e.g. '14:02' into the clumsy 'czternasta i dwie minuty'."""
    def repl(m):
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23:
            return m.group(0)
        words = _PL_HOURS[hour]
        mins = _pl_minutes(minute)
        return f"{words} {mins}".strip()

    return re.sub(r'\b(\d{1,2}):([0-5]\d)\b', repl, text)


def sanitize_for_tts(text, lang_code='pl'):
    """
    Make text pronounceable by a non-English TTS voice.
    - Clock times (Polish) get spelled out as words: "14:02" -> "czternasta zero dwie"
    - Phonetic replacements (whole words only, longest match first)
    - ALL-CAPS words (2+ letters) get spelled out: "API" -> "A P I"
    """
    if lang_code == 'pl':
        text = normalize_times_pl(text)

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


def _is_our_tts(pid):
    """True if pid is alive and is one of our TTS processes — either a `say`
    command or the edge_speak.py helper — so we never kill someone else's
    process after PID reuse."""
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    try:
        out = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                             capture_output=True, text=True)
        cmd = out.stdout.strip()
        if 'edge_speak.py' in cmd:
            return True
        first = cmd.split()[0] if cmd else ''
        return os.path.basename(first) == 'say'
    except OSError:
        return False


def _session_marker(dir_path, session_id):
    safe = "".join(c for c in str(session_id or "default")
                   if c.isalnum() or c in "-_.") or "default"
    return os.path.join(dir_path, safe)


def _busy_marker(session_id):
    return _session_marker(BUSY_DIR, session_id)


def _set_session_marker(dir_path, session_id, on):
    """Postaw/zdejmij plikowy znacznik per-sesja dla nakładki. Ciche przy błędzie."""
    try:
        if on:
            os.makedirs(dir_path, exist_ok=True)
            with open(_session_marker(dir_path, session_id), "w") as f:
                f.write(str(int(time.time())))
        else:
            try:
                os.remove(_session_marker(dir_path, session_id))
            except FileNotFoundError:
                pass
    except OSError:
        pass


def set_session_busy(session_id, busy):
    """Ustaw/zdejmij znacznik 'ta sesja pracuje' (tryb 'think' nakładki).
    UserPromptSubmit -> busy=True, Stop -> busy=False."""
    _set_session_marker(BUSY_DIR, session_id, busy)


def set_session_attention(session_id, on):
    """Ustaw/zdejmij znacznik 'ta sesja czeka na użytkownika' (tryb 'attention').
    Notification -> on=True; UserPromptSubmit / PostToolUse / Stop -> on=False."""
    _set_session_marker(ATTENTION_DIR, session_id, on)


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
            if pid and _is_our_tts(pid):
                # Kill the whole process group (start_new_session made the TTS
                # process a group leader), so an edge helper's `afplay`/`say`
                # child dies with it.
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except OSError:
                    pass
            return None
        # Non-priority: bail out if still speaking or just finished
        if (pid and _is_our_tts(pid)) or (time.time() - ts) < 2.0:
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

    edge_voice = edge_voice_for(config) if config.get('engine') == 'edge' else None

    try:
        if edge_voice:
            # Detached helper: synthesizes via edge-tts and plays it, falling
            # back to `say` on any failure. Text + voices go through the env so
            # they never appear in `ps` and survive odd characters.
            payload = json.dumps({
                "edge_voice": edge_voice,
                "edge_rate": str(config.get('edge_rate', '+0%')),
                "text": text,
                "say_voice": voice,
                "say_rate": rate,
                "cache_max_mb": config.get('cache_max_mb', 100),
                # Syrena i obniżony głos KITT-a tylko w trybie Knight Rider
                # (chorus na miksie dobrany razem z tym pitchem, patrz edge_speak.py).
                "intro_sound": (config.get('intro_sound', 'kitt')
                                if config.get('knight_rider', True) else 'none'),
                "edge_pitch": ("-20Hz" if config.get('knight_rider', True) else "+0Hz"),
            })
            proc = subprocess.Popen(
                [sys.executable, EDGE_SPEAK_PATH],
                start_new_session=True,
                env={**os.environ, "SIMPLE_TTS_PAYLOAD": payload},
            )
        else:
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
