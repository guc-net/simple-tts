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

Audio is cached on disk (see audio_cache.py): a repeated phrase with the same
voice plays straight from cache and skips synthesis. The cache tracks per-entry
usage and is bounded by total size (`cache_max_mb`), evicting least-used-then-
oldest entries. Synthesis writes to a temp file in the cache dir and is
atomically moved into place on success.

Payload keys: edge_voice, edge_rate, text, say_voice, say_rate, cache_max_mb.
"""

import os
import subprocess
import sys
import tempfile

import audio_cache as ac

# Wall-clock cap for synthesis. Generous because the very first `uvx edge-tts`
# run downloads the package before it can synthesize; later runs are quick.
SYNTH_TIMEOUT = 30


def _say(payload):
    """Fallback: speak through the local macOS `say` command (blocking)."""
    try:
        subprocess.run(['say', '-v', payload['say_voice'],
                        '-r', str(payload['say_rate']), payload['text']])
    except OSError as e:
        print(f"edge_speak say fallback error: {e}", file=sys.stderr)


def _play(path):
    """Play a file with afplay; return True on success."""
    try:
        subprocess.run(['afplay', path])
        return True
    except OSError:
        return False


def _payload_from_env():
    import json
    raw = os.environ.get('SIMPLE_TTS_PAYLOAD')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"edge_speak bad payload: {e}", file=sys.stderr)
        return None


def main():
    payload = _payload_from_env()
    if not payload:
        return

    text = payload.get('text', '')
    if not text:
        return

    key = ac.key_for(payload)
    cache_file = ac.cache_path(payload)

    # Cache hit: play straight from disk, record the use, skip synthesis.
    try:
        hit = os.path.getsize(cache_file) > 0
    except OSError:
        hit = False
    if hit:
        ac.record_hit(key)
        if not _play(cache_file):
            _say(payload)
        return

    # Cache miss: synthesize to a temp file in the cache dir, then store + play.
    os.makedirs(ac.CACHE_DIR, exist_ok=True)
    ac.sweep_temp()
    fd, tmp = tempfile.mkstemp(prefix=ac.TMP_PREFIX, suffix='.mp3', dir=ac.CACHE_DIR)
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
            os.replace(tmp, cache_file)
            tmp = None
            ac.record_store(key, text, payload['edge_voice'],
                            payload.get('edge_rate', '+0%'), os.path.getsize(cache_file))
            max_mb = payload.get('cache_max_mb', ac.DEFAULT_MAX_MB)
            ac.evict(int(float(max_mb) * 1024 * 1024))
            play_path = cache_file
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
