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

When `intro_sound` is set (e.g. "kitt"), the synthesized speech is mixed under
a looping background sound with a 1 s intro and a ~1 s outro that ends in the
sound's quiet valley (see _mix_kitt) — the mix is done at playback with ffmpeg,
so the on-disk cache always holds the plain speech and the effect toggles
instantly with config. Missing ffmpeg / sound file → the plain speech plays.

Payload keys: edge_voice, edge_rate, text, say_voice, say_rate, cache_max_mb,
intro_sound.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

import audio_cache as ac

# Obwiednia głośności odtwarzanego audio dla nakładki KITT (modulator „gada"
# w rytm tego, co słychać). Zapisywana tuż przed afplay; nakładka ją czyta.
SPEAK_STATE_PATH = os.path.expanduser("~/.claude/simple-tts-speak.json")
_ENV_DT = 0.04            # okno obwiedni (s)
_ENV_LO, _ENV_HI = -50.0, -15.0   # dB -> 0..1 (dolina syreny .. szczyt wyjca)

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


def _envelope(path):
    """Znormalizowana obwiednia RMS (0..1) odtwarzanego audio, okno _ENV_DT,
    przez ffmpeg astats. Pusta lista przy jakimkolwiek problemie."""
    n = int(_ENV_DT * 8000)
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-af',
           f'aresample=8000,asetnsamples=n={n}:p=0,'
           f'astats=metadata=1:reset=1,'
           f'ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-',
           '-f', 'null', '-']
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    env = []
    for line in out.splitlines():
        if 'RMS_level=' not in line:
            continue
        try:
            v = float(line.split('=')[1])
        except (ValueError, IndexError):
            continue
        if v != v or v <= -120:                 # nan / -inf (cisza)
            env.append(0.0)
        else:
            env.append(max(0.0, min(1.0, (v - _ENV_LO) / (_ENV_HI - _ENV_LO))))
    return env


def _write_speak_envelope(path, lead=0.0):
    """Policz obwiednię SAMEGO GŁOSU `path` (bez syreny) i zapisz stan mowy dla
    nakładki. `lead` (s) dosuwa obwiednię ciszą z przodu, gdy przed głosem gra
    intro syreny — modulator jest wtedy płaski i rusza dopiero z głosem."""
    if not shutil.which('ffmpeg'):
        return
    try:
        env = _envelope(path)
    except Exception:
        return
    if not env:
        return
    if lead > 0:
        env = [0.0] * int(round(lead / _ENV_DT)) + env
    try:
        tmp = SPEAK_STATE_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'start': time.time(), 'dt': _ENV_DT, 'env': env}, f)
        os.replace(tmp, SPEAK_STATE_PATH)
    except OSError:
        pass


def _sound_path(name):
    """Absolute path to a bundled background sound (e.g. 'kitt' -> sounds/kitt.mp3)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'sounds', f'{name}.mp3')


def _audio_duration(path):
    """Seconds of audio in `path` via ffprobe (raises on any failure)."""
    res = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True, timeout=10,
    )
    return float(res.stdout.strip())


# Background-sound mix tuning. The KITT loop runs in ~1.28 s cycles, each ending
# in a quiet valley at t ≈ V0 + n·PERIOD s. We end the background at the first
# valley AFTER the speech (INTRO + speech + ≥MIN_OUTRO) so it dies in a natural
# quiet point, not mid-swoosh, with a short fade to true zero.
_INTRO = 1.0        # seconds of sound before speech starts
_PERIOD = 1.28      # KITT loop cycle length
_V0 = 0.04          # time of the first valley
_MIN_OUTRO = 0.35   # minimum tail after speech before the ending valley
_FADE = 0.10        # fade-to-zero at the very end


def _mix_kitt(speech_path, payload):
    """Mix `speech_path` under the configured background sound and return a temp
    mp3 to play, or None (caller falls back to the plain speech) when disabled,
    ffmpeg/ffprobe or the sound file is missing, or ffmpeg fails."""
    name = payload.get('intro_sound')          # absent → feature off (tests)
    if not name or name == 'none':
        return None
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        return None
    sound = _sound_path(name)
    if not os.path.exists(sound):
        return None
    try:
        dur = _audio_duration(speech_path)
    except Exception:
        return None
    if dur <= 0:
        return None

    n = math.ceil((_INTRO + dur + _MIN_OUTRO - _V0) / _PERIOD)
    end = _V0 + n * _PERIOD
    fade_start = max(0.0, end - _FADE)
    delay_ms = int(_INTRO * 1000)
    graph = (
        f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,"
        f"atrim=0:{end:.3f},asetpts=PTS-STARTPTS,volume=1.7,"
        f"afade=t=out:st={fade_start:.3f}:d={_FADE}[kitt];"
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.3,"
        f"adelay={delay_ms}|{delay_ms},apad=whole_dur={end:.3f},asplit=2[sc][sp];"
        f"[kitt][sc]sidechaincompress=threshold=0.04:ratio=9:attack=15:"
        f"release=250:makeup=1[duck];"
        f"[duck][sp]amix=inputs=2:duration=longest:normalize=0,"
        f"alimiter=limit=0.95[mix]"
    )
    fd, out = tempfile.mkstemp(prefix='simple-tts-kitt-', suffix='.mp3')
    os.close(fd)
    try:
        res = subprocess.run(
            ['ffmpeg', '-y', '-stream_loop', '-1', '-i', sound, '-i', speech_path,
             '-filter_complex', graph, '-map', '[mix]',
             '-ac', '2', '-ar', '44100', '-b:a', '192k', out],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        res = None
    if res is None or res.returncode != 0 or _empty(out):
        try:
            os.unlink(out)
        except OSError:
            pass
        return None
    return out


def _empty(path):
    try:
        return os.path.getsize(path) == 0
    except OSError:
        return True


def _play_speech(path, payload):
    """Play the speech, mixing in the background sound when enabled; on any mix
    failure play the plain speech. Returns True if something played."""
    mixed = _mix_kitt(path, payload)
    # Obwiednię liczymy tylko w trybie KITT (gdy nakładka jej użyje) — to samo
    # kryterium, co syrena: intro_sound != none/absent. ZAWSZE z samego głosu
    # (path), a gdy gra miks, dosunięta o intro syreny, żeby modulator ruszał
    # z głosem (i był czas na przełączenie animacji podczas pierwszego wycia).
    if payload.get('intro_sound') not in (None, 'none'):
        _write_speak_envelope(path, _INTRO if mixed else 0.0)
    if mixed:
        try:
            if _play(mixed):
                return True
        finally:
            try:
                os.unlink(mixed)
            except OSError:
                pass
    return _play(path)


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
        if not _play_speech(cache_file, payload):
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

        if not _play_speech(play_path, payload):
            _say(payload)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


if __name__ == '__main__':
    main()
