#!/usr/bin/env python3
"""
Detached TTS helper for simple-tts' edge-tts engine.

Launched (and detached) by tts_utils.speak() with a JSON payload in the
SIMPLE_TTS_PAYLOAD env var. It synthesizes speech with Microsoft edge-tts
(run out-of-process via `uvx edge-tts`, so the plugin keeps zero dependencies),
plays the resulting mp3 with macOS `afplay`, and falls back to the local `say`
command on ANY failure — offline, `uvx` missing, synthesis timeout, or an empty
result. Because speak() spawns it with start_new_session=True, this process is
its own group leader, so a priority interrupt can kill it together with its
`afplay`/`say` child via killpg.

Audio is cached on disk: the mp3 is stored under CACHE_DIR named by a SHA-256
checksum of (engine, voice, rate, text), so repeating the same phrase with the
same voice plays straight from cache and skips synthesis entirely. Synthesis
writes to a temp file in CACHE_DIR and is atomically moved into place on
success; stale temp files (from an interrupted synth) and an over-large cache
are pruned opportunistically.

Payload keys: edge_voice, edge_rate, text, say_voice, say_rate.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

# Wall-clock cap for synthesis. Generous because the very first `uvx edge-tts`
# run downloads the package before it can synthesize; later runs are quick.
SYNTH_TIMEOUT = 30

# Persistent audio cache (survives across sessions, unlike $TMPDIR).
CACHE_DIR = os.path.expanduser("~/.claude/simple-tts-audio-cache")
# In-progress synth files use this prefix so they are never mistaken for, or
# counted as, finished cache entries (which are named "<sha256hex>.mp3").
TMP_PREFIX = ".synthtmp-"
# Cap on stored phrases; oldest (least-recently-played) are pruned past this.
MAX_CACHE_ENTRIES = 256
# A temp file older than this was orphaned by a killed synth — safe to sweep.
TMP_MAX_AGE = 60


def _cache_path(payload):
    """Content-addressed cache path: SHA-256 over engine, voice, rate, text."""
    parts = ["edge", payload.get("edge_voice", ""),
             payload.get("edge_rate", "+0%"), payload.get("text", "")]
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.mp3")


def _say(payload):
    """Fallback: speak through the local macOS `say` command (blocking)."""
    try:
        subprocess.run(['say', '-v', payload['say_voice'],
                        '-r', str(payload['say_rate']), payload['text']])
    except OSError as e:
        print(f"edge_speak say fallback error: {e}", file=sys.stderr)


def _sweep_temp():
    """Remove temp files orphaned by an interrupted synth (killpg/crash)."""
    now = time.time()
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return
    for name in names:
        if not (name.startswith(TMP_PREFIX) and name.endswith(".mp3")):
            continue
        path = os.path.join(CACHE_DIR, name)
        try:
            if now - os.path.getmtime(path) > TMP_MAX_AGE:
                os.unlink(path)
        except OSError:
            pass


def _prune_cache():
    """Keep at most MAX_CACHE_ENTRIES entries, dropping the oldest by mtime."""
    try:
        entries = [os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR)
                   if n.endswith(".mp3") and not n.startswith(TMP_PREFIX)]
    except OSError:
        return
    if len(entries) <= MAX_CACHE_ENTRIES:
        return
    entries.sort(key=lambda p: _mtime(p))
    for path in entries[:len(entries) - MAX_CACHE_ENTRIES]:
        try:
            os.unlink(path)
        except OSError:
            pass


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _play(path):
    """Play a file with afplay; return True on success."""
    try:
        subprocess.run(['afplay', path])
        return True
    except OSError:
        return False


def main():
    raw = os.environ.get('SIMPLE_TTS_PAYLOAD')
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"edge_speak bad payload: {e}", file=sys.stderr)
        return

    text = payload.get('text', '')
    if not text:
        return

    cache_path = _cache_path(payload)

    # Cache hit: play straight from disk, mark recently used, skip synthesis.
    try:
        hit = os.path.getsize(cache_path) > 0
    except OSError:
        hit = False
    if hit:
        try:
            os.utime(cache_path, None)
        except OSError:
            pass
        if not _play(cache_path):
            _say(payload)
        return

    # Cache miss: synthesize to a temp file in CACHE_DIR, then store + play.
    os.makedirs(CACHE_DIR, exist_ok=True)
    _sweep_temp()
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, suffix='.mp3', dir=CACHE_DIR)
    os.close(fd)
    try:
        try:
            result = subprocess.run(
                ['uvx', 'edge-tts',
                 '--voice', payload['edge_voice'],
                 '--rate', payload.get('edge_rate', '+0%'),
                 '--text', text,
                 '--write-media', tmp],
                capture_output=True, timeout=SYNTH_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            _say(payload)
            return

        if result.returncode != 0 or os.path.getsize(tmp) == 0:
            _say(payload)
            return

        # Store atomically so a concurrent reader never sees a partial file.
        try:
            os.replace(tmp, cache_path)
            tmp = None
            _prune_cache()
            play_path = cache_path
        except OSError:
            play_path = tmp  # storing failed; still play what we synthesized

        if not _play(play_path):
            _say(payload)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


if __name__ == '__main__':
    main()
