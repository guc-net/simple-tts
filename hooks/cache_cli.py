#!/usr/bin/env python3
"""
Manage the simple-tts audio cache from the command line (used by `/tts cache`).

  python3 hooks/cache_cli.py stats        # show entries, play counts, size
  python3 hooks/cache_cli.py prune        # evict down to the configured budget
  python3 hooks/cache_cli.py prune --max-mb 50
  python3 hooks/cache_cli.py clear        # delete everything
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audio_cache as ac  # noqa: E402


def _max_mb():
    try:
        from tts_utils import load_config
        return float(load_config().get("cache_max_mb", ac.DEFAULT_MAX_MB))
    except Exception:
        return float(ac.DEFAULT_MAX_MB)


def _human(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _when(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (ValueError, OSError, TypeError):
        return "?"


def cmd_stats():
    data = ac.stats()
    limit = _max_mb()
    print(f"simple-tts audio cache — {data['count']} wpisów, "
          f"{_human(data['total_bytes'])} / limit {limit:.0f} MB")
    print(f"katalog: {ac.CACHE_DIR}")
    if not data["entries"]:
        print("(pusty)")
        return
    print(f"\n{'odtw.':>6}  {'ostatnio':16}  {'rozmiar':>8}  tekst")
    for e in data["entries"]:
        text = e["text"] or "(brak metadanych)"
        if len(text) > 60:
            text = text[:57] + "…"
        print(f"{e['plays']:>6}  {_when(e['last_used']):16}  "
              f"{_human(e['size']):>8}  {text}")


def cmd_prune(max_mb):
    freed = ac.evict(int(max_mb * 1024 * 1024))
    if freed:
        print(f"Zwolniono {_human(freed)} (limit {max_mb:.0f} MB).")
    else:
        print(f"Nic do usunięcia — cache mieści się w limicie {max_mb:.0f} MB.")


def cmd_clear():
    removed = ac.clear()
    print(f"Wyczyszczono cache audio ({removed} plików usuniętych).")


def main(argv):
    cmd = argv[0] if argv else "stats"
    if cmd == "stats":
        cmd_stats()
    elif cmd == "clear":
        cmd_clear()
    elif cmd == "prune":
        max_mb = _max_mb()
        if "--max-mb" in argv:
            try:
                max_mb = float(argv[argv.index("--max-mb") + 1])
            except (IndexError, ValueError):
                print("Użycie: prune [--max-mb N]", file=sys.stderr)
                return 2
        cmd_prune(max_mb)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
