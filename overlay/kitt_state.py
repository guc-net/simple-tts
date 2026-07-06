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

import json
import os
import subprocess
import time

CONFIG_PATH = os.path.expanduser("~/.claude/simple-tts-config.json")
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


def overlay_enabled():
    """True gdy plugin skonfigurowany i tryb Knight Rider włączony."""
    cfg = _read_json(CONFIG_PATH)
    if cfg is None:
        return False
    return bool(cfg.get("knight_rider", True))


def is_speaking():
    """True gdy leci dźwięk TTS — żyje proces odtwarzania (afplay lub say).
    Wykrywa mowę KAŻDEJ sesji i tylko podczas realnego odtwarzania."""
    for name in AUDIO_PROCS:
        try:
            r = subprocess.run(["pgrep", "-x", name],
                               capture_output=True, text=True)
        except OSError:
            continue
        if r.stdout.strip():
            return True
    return False


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
