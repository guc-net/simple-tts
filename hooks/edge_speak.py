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

Payload keys: edge_voice, edge_rate, text, say_voice, say_rate.
"""

import json
import os
import subprocess
import sys
import tempfile

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

    fd, mp3 = tempfile.mkstemp(prefix='simple-tts-', suffix='.mp3')
    os.close(fd)
    try:
        try:
            result = subprocess.run(
                ['uvx', 'edge-tts',
                 '--voice', payload['edge_voice'],
                 '--rate', payload.get('edge_rate', '+0%'),
                 '--text', text,
                 '--write-media', mp3],
                capture_output=True, timeout=SYNTH_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            _say(payload)
            return

        if result.returncode != 0 or os.path.getsize(mp3) == 0:
            _say(payload)
            return

        try:
            subprocess.run(['afplay', mp3])
        except OSError:
            _say(payload)
    finally:
        try:
            os.unlink(mp3)
        except OSError:
            pass


if __name__ == '__main__':
    main()
