"""Wybór trybu nakładki KITT ze stanu simple-tts (tylko stdlib, testowalne).

Agregacja po WSZYSTKICH sesjach Claude Code:
  speak -> ktokolwiek właśnie odtwarza dźwięk (żywy proces afplay/say)
  think -> ktokolwiek pracuje (świeży plik w katalogu busy)
  idle  -> nic z powyższych
  None  -> nakładka wyłączona (brak configu lub knight_rider=false)

Precedencja: speak > think > idle (mowa kogokolwiek wygrywa z myśleniem).
„speak" jest wykrywane po realnym procesie odtwarzania, więc modulator rusza
się dokładnie wtedy, gdy leci dźwięk (a nie podczas syntezowania/ładowania).

Ścieżki jako stałe modułu, żeby testy mogły je monkeypatchować.
"""

import ctypes
import json
import os
import subprocess
import time

CONFIG_PATH = os.path.expanduser("~/.claude/simple-tts-config.json")
# PID + ts ostatniego procesu TTS (dowolnej sesji) — brama dla detekcji audio.
STATE_PATH = os.path.expanduser("~/.claude/simple-tts-state.json")
# Katalog znaczników „sesja pracuje": jeden plik na sesję (touch/rm przez hooki).
BUSY_DIR = os.path.expanduser("~/.claude/simple-tts-busy.d")
BUSY_STALE_SEC = 900          # znacznik starszy niż 15 min = osierocony, ignoruj
AUDIO_PROCS = ("afplay", "say")


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# Nakładka woła current_mode() kilka razy na sekundę — config i state parsujemy
# tylko, gdy plik faktycznie się zmienił (stat zamiast open+json za każdym razem).
_JSON_CACHE = {}


def _read_json_cached(path):
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        _JSON_CACHE.pop(path, None)
        return None
    hit = _JSON_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    data = _read_json(path)
    _JSON_CACHE[path] = (key, data)
    return data


def overlay_enabled():
    """True gdy plugin skonfigurowany i tryb Knight Rider włączony."""
    cfg = _read_json_cached(CONFIG_PATH)
    if cfg is None:
        return False
    return bool(cfg.get("knight_rider", True))


_PROC_ALL_PIDS = 1
try:
    _libc = ctypes.CDLL(None, use_errno=True)
    _libc.proc_listpids.restype = ctypes.c_int
    _libc.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_int]
    _libc.proc_name.restype = ctypes.c_int
    _libc.proc_name.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    _HAVE_LIBPROC = True
except (OSError, AttributeError):
    _HAVE_LIBPROC = False


def _running_process_names():
    """Zbiór nazw (comm) żywych procesów przez libproc — bez forka/spawnu.
    None gdy libproc niedostępne (wtedy is_speaking użyje pgrep)."""
    if not _HAVE_LIBPROC:
        return None
    try:
        n = _libc.proc_listpids(_PROC_ALL_PIDS, 0, None, 0)
        if n <= 0:
            return set()
        count = n // ctypes.sizeof(ctypes.c_int32)
        arr = (ctypes.c_int32 * count)()
        n = _libc.proc_listpids(_PROC_ALL_PIDS, 0, arr, ctypes.sizeof(arr))
        if n <= 0:
            return set()
        buf = ctypes.create_string_buffer(256)
        names = set()
        for i in range(n // ctypes.sizeof(ctypes.c_int32)):
            pid = arr[i]
            if pid > 0 and _libc.proc_name(pid, buf, 256) > 0:
                names.add(buf.value.decode("utf-8", "replace"))
        return names
    except Exception:
        return None


def _pgrep_speaking():
    for name in AUDIO_PROCS:
        try:
            r = subprocess.run(["pgrep", "-x", name],
                               capture_output=True, text=True)
        except OSError:
            continue
        if r.stdout.strip():
            return True
    return False


def _tts_active():
    """True gdy żyje proces TTS zapisany przez simple-tts (dowolna sesja).
    Tania brama: w idle nie ma po co skanować procesów."""
    st = _read_json_cached(STATE_PATH)
    pid = st.get("pid") if st else None
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def is_speaking():
    """True gdy leci dźwięk TTS — jest aktywny proces TTS ORAZ żyje proces
    odtwarzania (afplay/say). Bramka _tts_active() sprawia, że w idle nic nie
    skanujemy, a fałszywe afplay innych apek nie liczą się jako mowa."""
    if not _tts_active():
        return False
    names = _running_process_names()
    if names is None:
        return _pgrep_speaking()
    return any(p in names for p in AUDIO_PROCS)


def is_busy():
    """True gdy którakolwiek sesja pracuje (świeży znacznik w BUSY_DIR)."""
    try:
        names = os.listdir(BUSY_DIR)
    except OSError:
        return False
    now = time.time()
    for name in names:
        try:
            if now - os.path.getmtime(os.path.join(BUSY_DIR, name)) < BUSY_STALE_SEC:
                return True
        except OSError:
            pass
    return False


def current_mode():
    """'speak' | 'think' | 'idle' | None (wyłączone)."""
    if not overlay_enabled():
        return None
    if is_speaking():
        return "speak"
    if is_busy():
        return "think"
    return "idle"
