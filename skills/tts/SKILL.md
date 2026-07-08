---
description: "Mute or unmute simple-tts speech, toggle Knight Rider mode (KITT siren + scanner overlay), pick the overlay theme (kitt/cylon/hal/ekg/matrix/lava), and manage the audio cache. Usage: /simple-tts:tts on|off|status|knight-rider [on|off]|theme [name]|cache [stats|prune|clear]."
user_invocable: true
---

# TTS on/off

Plugin skills are namespaced, so this is invoked as **`/simple-tts:tts`** (e.g. `/simple-tts:tts cache stats`). A bare `/tts` is only possible via a personal `~/.claude/commands/tts.md` wrapper.

Toggle simple-tts speech via the `enabled` flag in `~/.claude/simple-tts-config.json`. The hooks stay registered; `"enabled": false` just makes them silent. No argument or anything other than `on`/`off`/`cache` means **status**.

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

## /tts knight-rider [on|off]   (alias: sound)

Toggle **Knight Rider mode** — the `knight_rider` config key. One switch for both:
the KITT siren bed mixed under the voice (`intro_sound`, needs `ffmpeg`) **and** the
floating scanner overlay animation (idle scanner / thinking / speaking). `on` sets
`true`, `off` sets `false`; no argument reports the current value. Default is on.

```bash
python3 -c "
import json, os, sys
p = os.path.expanduser('~/.claude/simple-tts-config.json')
with open(p) as f: c = json.load(f)
arg = sys.argv[1] if len(sys.argv) > 1 else ''
if arg in ('on','off'):
    c['knight_rider'] = (arg == 'on')
    with open(p, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
print('knight_rider =', c.get('knight_rider', True))
" ${ARG:-}
```

Pass the user's `on`/`off` as the argument. Confirm the resulting state (e.g. "Tryb Knight Rider włączony (syrena + skaner)." / "…wyłączony."). The overlay reacts within a second; the siren applies to the next spoken line.

## /tts theme [name]

Pick the **overlay animation theme** — the `overlay_theme` config key. Available
themes: `kitt` (Knight Rider scanner, default), `cylon` (Battlestar Galactica eye),
`hal` (HAL 9000 red eye), `ekg` (heart monitor trace), `matrix` (digital rain),
`lava` (plasma). The running overlay picks the change up live (within a second),
no restart needed. No argument reports the current theme and lists the options.

```bash
python3 -c "
import json, os, sys
p = os.path.expanduser('~/.claude/simple-tts-config.json')
themes = ('kitt', 'cylon', 'hal', 'ekg', 'matrix', 'lava')
with open(p) as f: c = json.load(f)
arg = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
if arg:
    if arg not in themes:
        print('nieznany motyw:', arg, '| dostępne:', ', '.join(themes)); sys.exit(1)
    c['overlay_theme'] = arg
    with open(p, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
print('overlay_theme =', c.get('overlay_theme', 'kitt'))
" ${ARG:-}
```

Pass the user's theme name as the argument. Confirm the resulting theme in Polish
(e.g. "Motyw nakładki: hal — czerwone oko HAL 9000."). Remind that the overlay
itself is toggled by `knight-rider on|off` if it is currently off.

## /tts status

Read the config and report:
- enabled: `enabled` key (missing key = enabled)
- voice, rate, language
- Knight Rider mode: `knight_rider` key (missing key = on) — siren bed + scanner overlay
- overlay theme: `overlay_theme` key (missing key = kitt)
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
