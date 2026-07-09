#!/usr/bin/env python3
"""Config read/write helper for the /simple-tts:tts skill.

Replaces the per-subcommand inline `python3 -c "..."` blocks: the skill just
shells out to this one CLI. Stdlib-only, same as the rest of the plugin.

Usage:
  python3 hooks/config_cli.py get <key> [default]     # raw stored value or default
  python3 hooks/config_cli.py set <key> <value>...     # atomic multi-key write
  python3 hooks/config_cli.py show                      # effective (merged) config

`set` infers value types: true/false -> bool, integers -> int, else string.
It fails (exit 2) when the config file does not exist — run /simple-tts-setup.
`get`/`show` never write; `get` prints the default (or empty) when unconfigured.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tts_utils import CONFIG_PATH, load_config  # noqa: E402


def _coerce(value):
    """Infer a JSON-ish type from a CLI string: bool, int, else str."""
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _load_raw():
    """The config file exactly as stored (no DEFAULT_CONFIG merge), or None."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def cmd_get(args):
    key = args[0]
    default = args[1] if len(args) > 1 else ""
    raw = _load_raw() or {}
    print(raw.get(key, default))
    return 0


def cmd_set(args):
    if not args or len(args) % 2 != 0:
        print("usage: config_cli.py set <key> <value> [<key> <value> ...]", file=sys.stderr)
        return 1
    raw = _load_raw()
    if raw is None:
        print("simple-tts not configured — run /simple-tts-setup first", file=sys.stderr)
        return 2
    for i in range(0, len(args), 2):
        raw[args[i]] = _coerce(args[i + 1])
    with open(CONFIG_PATH, "w") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
    # Echo back the keys we just set, so the skill can confirm.
    for i in range(0, len(args), 2):
        print(f"{args[i]} = {json.dumps(raw[args[i]], ensure_ascii=False)}")
    return 0


def cmd_show(_args):
    cfg = load_config()
    if cfg is None:
        print("simple-tts not configured — run /simple-tts-setup first", file=sys.stderr)
        return 2
    keys = [
        "enabled", "voice", "rate", "language", "engine",
        "overlay_theme", "knight_rider", "voice_howl", "voice_distortion",
        "quiet_hours", "cache_max_mb",
    ]
    for k in keys:
        if k in cfg:
            print(f"{k} = {json.dumps(cfg[k], ensure_ascii=False)}")
    return 0


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    cmd, rest = argv[0], argv[1:]
    handlers = {"get": cmd_get, "set": cmd_set, "show": cmd_show}
    handler = handlers.get(cmd)
    if handler is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return handler(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
