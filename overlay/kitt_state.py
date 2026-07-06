"""Wybór trybu nakładki KITT ze stanu simple-tts (tylko stdlib, testowalne).

  speak -> simple-tts właśnie mówi (żywy proces TTS w simple-tts-state.json)
  think -> Claude pracuje (busy ustawiony przez hook UserPromptSubmit)
  idle  -> nic z powyższych
  None  -> nakładka wyłączona (brak configu lub overlay_enabled=false) -> nic nie rysuj

Ścieżki jako stałe modułu, żeby testy mogły je monkeypatchować (jak w conftest).
"""

import json
import os
import subprocess

STATE_PATH = os.path.expanduser("~/.claude/simple-tts-state.json")
BUSY_PATH = os.path.expanduser("~/.claude/simple-tts-busy")
CONFIG_PATH = os.path.expanduser("~/.claude/simple-tts-config.json")


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
    """True gdy PID z simple-tts-state.json żyje i jest naszym procesem TTS
    (`say` albo edge_speak.py) — analogicznie do tts_utils._is_our_tts."""
    st = _read_json(STATE_PATH)
    if not st:
        return False
    pid = st.get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True)
    except OSError:
        return False
    cmd = out.stdout.strip()
    if not cmd:
        return False
    if "edge_speak.py" in cmd:
        return True
    return os.path.basename(cmd.split()[0]) == "say"


def is_busy():
    """True gdy Claude pracuje (plik busy = '1')."""
    try:
        with open(BUSY_PATH) as f:
            return f.read().strip() == "1"
    except OSError:
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
