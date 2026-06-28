---
description: "Mute or unmute simple-tts speech and manage the audio cache. Usage: /tts on, /tts off, /tts status, /tts cache [stats|prune|clear]."
user_invocable: true
---

# TTS on/off

Toggle simple-tts speech via the `enabled` flag in `~/.claude/simple-tts-config.json`. The hooks stay registered; `"enabled": false` just makes them silent. No argument or anything other than `on`/`off` means **status**.

If `~/.claude/simple-tts-config.json` does not exist, stop and tell the user to run `/simple-tts-setup` first.

## /tts off

```bash
python3 -c "
import json, os
p = os.path.expanduser('~/.claude/simple-tts-config.json')
with open(p) as f: c = json.load(f)
c['enabled'] = False
with open(p, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
print('muted')
"
```

Confirm: "TTS muted. Re-enable with `/tts on`." Do NOT add a TTS tag to this response — the user just asked for silence.

## /tts on

Same as above with `c['enabled'] = True`. Confirm: "TTS unmuted." You may add a TTS tag again from this response on.

## /tts status

Read the config and report:
- enabled: `enabled` key (missing key = enabled)
- voice, rate, language
- quiet hours, if `quiet_hours` is set (speech is silenced between start and end)

## /tts cache [stats|prune|clear]

Manages the on-disk edge-tts audio cache via `cache_cli.py`. No subcommand = `stats`.
Resolve the script path (works whether invoked as an installed plugin or from the repo), then run it:

```bash
CLI="$(ls "${CLAUDE_PLUGIN_ROOT:-}/hooks/cache_cli.py" 2>/dev/null \
  || ls ~/.claude/plugins/cache/*/simple-tts/*/hooks/cache_cli.py 2>/dev/null | sort -V | tail -1 \
  || ls "$PWD/hooks/cache_cli.py" 2>/dev/null)"
python3 "$CLI" stats
```

- `/tts cache` or `/tts cache stats` → run with `stats`: prints each cached phrase, its play count, last-used time and size, plus total size vs the `cache_max_mb` budget. Show the output to the user. Safe to add a TTS tag.
- `/tts cache prune` → run with `prune` (optionally `prune --max-mb N`): evicts least-used-then-oldest entries down to the budget and reports bytes freed.
- `/tts cache clear` → run with `clear`: deletes the whole cache. Confirm what was removed.

The size budget is the `cache_max_mb` config key (default 100). Eviction also runs automatically after each new synthesis.
