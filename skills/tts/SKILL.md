---
description: "Mute or unmute simple-tts speech, toggle the scanner overlay, the voice howl (siren) and distortion, pick the overlay theme (kitt/cylon/spark), and manage the audio cache. Usage: /simple-tts:tts on|off|status|knight-rider [on|off]|howl [on|off|auto]|distortion [on|off|auto]|theme [name]|cache [stats|prune|clear]."
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

Toggle the **scanner overlay** — the `knight_rider` config key. Controls only the
floating overlay animation (idle scanner / thinking / speaking). `on` sets `true`,
`off` sets `false`; no argument reports the current value. Default is on. (The voice
howl and distortion are separate — see `/tts howl` and `/tts distortion`.)

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

Pass the user's `on`/`off` as the argument. Confirm the resulting state (e.g. "Skaner włączony." / "…wyłączony."). The overlay reacts within a second.

## /tts howl [on|off|auto]

Toggle the **siren "howl"** (wyjec) mixed under the voice — the `voice_howl` config
key (needs `ffmpeg`). Values: **`auto`** (default) = howl plays **only with the KITT
overlay theme**, all other themes speak without it; **`on`** = always; **`off`** =
never. Independent of the voice distortion. No argument reports the current value.

```bash
python3 -c "
import json, os, sys
p = os.path.expanduser('~/.claude/simple-tts-config.json')
with open(p) as f: c = json.load(f)
arg = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
if arg in ('on','off','auto'):
    c['voice_howl'] = arg
    with open(p, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
print('voice_howl =', c.get('voice_howl', 'auto'))
" ${ARG:-}
```

Pass the user's argument. Confirm (e.g. "Wyjec: auto (tylko przy motywie KITT)." / "…zawsze." / "…nigdy."). Applies to the next spoken line.

## /tts distortion [on|off|auto]

Toggle the **voice distortion** (KITT-style −20 Hz pitch) — the `voice_distortion`
config key. Values: **`auto`** (default) = distortion on for the KITT-family themes
(`kitt`, `cylon`), **off for `spark`** (plain voice); **`on`** = always; **`off`** =
never. Independent of the howl. No argument reports the current value.

```bash
python3 -c "
import json, os, sys
p = os.path.expanduser('~/.claude/simple-tts-config.json')
with open(p) as f: c = json.load(f)
arg = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
if arg in ('on','off','auto'):
    c['voice_distortion'] = arg
    with open(p, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
print('voice_distortion =', c.get('voice_distortion', 'auto'))
" ${ARG:-}
```

Pass the user's argument. Confirm (e.g. "Zniekształcenie: auto (kitt/cylon tak, spark nie)." / "…zawsze." / "…nigdy."). Applies to the next spoken line.

## /tts theme [name]

Pick the **overlay animation theme** — the `overlay_theme` config key. Available
themes: `kitt` (Knight Rider scanner, default; turns into KARR's yellow scanner
when waiting), `cylon` (Battlestar Galactica red eye), `spark` (green cat-eye lens
with a spark stream; splits one lens per working agent, blue when waiting). The
running overlay picks the change up live (within a second), no restart needed. No
argument reports the current theme and lists the options.

```bash
python3 -c "
import json, os, sys
p = os.path.expanduser('~/.claude/simple-tts-config.json')
themes = ('kitt', 'cylon', 'spark')
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
(e.g. "Motyw nakładki: spark — zielone kocie oko."). Remind that the overlay
itself is toggled by `knight-rider on|off` if it is currently off.

## /tts status

Read the config and report:
- enabled: `enabled` key (missing key = enabled)
- voice, rate, language
- scanner overlay: `knight_rider` key (missing key = on)
- overlay theme: `overlay_theme` key (missing key = kitt)
- voice howl (siren): `voice_howl` key (missing = auto — only with the KITT theme)
- voice distortion: `voice_distortion` key (missing = auto — kitt/cylon yes, spark no)
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
