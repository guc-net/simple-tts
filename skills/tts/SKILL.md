---
description: "Mute or unmute simple-tts speech, pick the overlay theme (spark/kitt/cylon) or turn the overlay off, tune the voice howl (siren) and distortion, and manage the audio cache. Usage: /simple-tts:tts on|off|status|theme [name|off]|howl [on|off|auto]|distortion [on|off|auto]|cache [stats|prune|clear]."
user_invocable: true
---

# TTS control

Plugin skills are namespaced, so this is invoked as **`/simple-tts:tts`** (e.g. `/simple-tts:tts theme spark`). A bare `/tts` is only possible via a personal `~/.claude/commands/tts.md` wrapper.

If `~/.claude/simple-tts-config.json` does not exist, stop and tell the user to run `/simple-tts-setup` first — every subcommand below (except `cache`) writes through `config_cli.py`, which refuses to run unconfigured.

## Shared: resolve the helper CLIs

All config reads/writes go through `hooks/config_cli.py` (`get`/`set`/`show`); the cache goes through `hooks/cache_cli.py`. Resolve the path once (works whether run as an installed plugin or from the repo), then reuse `$CLI`:

```bash
CLI="$(ls "${CLAUDE_PLUGIN_ROOT:-}/hooks/config_cli.py" 2>/dev/null \
  || ls ~/.claude/plugins/cache/*/simple-tts/*/hooks/config_cli.py 2>/dev/null | sort -V | tail -1 \
  || ls "$PWD/hooks/config_cli.py" 2>/dev/null)"
```

`config_cli.py set` accepts one or more `key value` pairs and writes them atomically; it infers types (`true`/`false` → bool, integers → int, else string) and echoes back what it set.

## /tts off

```bash
python3 "$CLI" set enabled false
```

Confirm: "TTS muted. Re-enable with `/tts on`." Do NOT add a TTS tag to this response — the user just asked for silence.

## /tts on

```bash
python3 "$CLI" set enabled true
```

Confirm: "TTS unmuted." You may add a TTS tag again from this response on.

## /tts theme [name|off]

Controls the floating **overlay** — both which theme it shows (`overlay_theme`) and whether it runs at all (`knight_rider`). Available themes:

- **`spark`** — green cat-eye lens with a spark stream (**default**); splits one lens per working agent, blinks blue when waiting for you
- **`kitt`** — Knight Rider red scanner; turns into KARR's yellow scanner when waiting
- **`cylon`** — Battlestar Galactica wide red eye

Behaviour by argument:

- **no argument** → read the current state and present the list. Fetch it, then narrate the options above and mark the current one:
  ```bash
  echo "theme: $(python3 "$CLI" get overlay_theme spark) | overlay: $(python3 "$CLI" get knight_rider true)"
  ```
  If `overlay` is `false`, say the overlay is currently **off** (turn it on by picking a theme).
- **`spark` / `kitt` / `cylon`** → set that theme AND enable the overlay in one write:
  ```bash
  python3 "$CLI" set overlay_theme <name> knight_rider true
  ```
  Confirm in Polish (e.g. "Motyw nakładki: spark — zielone kocie oko."). The running overlay picks the change up live, no restart.
- **`off` / `none` / `brak`** → hide the overlay entirely (keeps the remembered theme):
  ```bash
  python3 "$CLI" set knight_rider false
  ```
  Confirm (e.g. "Nakładka wyłączona. Włącz wybierając motyw: `/tts theme spark`.").
- **anything else** → do not write; reply that the name is unknown and list `spark`, `kitt`, `cylon`, `off`.

The voice howl/distortion follow the theme automatically on `auto` (see below): spark = plain voice, kitt = siren + distortion, cylon = distortion only.

## /tts howl [on|off|auto]

The **siren "howl"** (wyjec) mixed under the voice — the `voice_howl` key (needs `ffmpeg`). Values: **`auto`** (default) = howl plays **only with the `kitt` theme**, all other themes speak without it; **`on`** = always; **`off`** = never. Independent of the distortion. No argument = report current.

```bash
python3 "$CLI" set voice_howl <on|off|auto>     # only when an argument was given
python3 "$CLI" get voice_howl auto              # to report the current value
```

Confirm (e.g. "Wyjec: auto (tylko przy motywie KITT)." / "…zawsze." / "…nigdy."). Applies to the next spoken line.

## /tts distortion [on|off|auto]

The **voice distortion** (KITT-style −20 Hz pitch) — the `voice_distortion` key. Values: **`auto`** (default) = on for the KITT-family themes (`kitt`, `cylon`), **off for `spark`** (plain voice); **`on`** = always; **`off`** = never. Independent of the howl. No argument = report current.

```bash
python3 "$CLI" set voice_distortion <on|off|auto>   # only when an argument was given
python3 "$CLI" get voice_distortion auto            # to report the current value
```

Confirm (e.g. "Zniekształcenie: auto (kitt/cylon tak, spark nie)." / "…zawsze." / "…nigdy."). Applies to the next spoken line.

## /tts status

Print the effective config in one shot:

```bash
python3 "$CLI" show
```

It lists: enabled, voice, rate, language, engine, overlay theme (`overlay_theme`, default spark), overlay on/off (`knight_rider`, default on), voice howl (`voice_howl`, default auto — only with the KITT theme), voice distortion (`voice_distortion`, default auto — kitt/cylon yes, spark no), quiet hours (if set) and the cache budget. Present it readably in Polish.

## /tts cache [stats|prune|clear]

Manages the on-disk edge-tts audio cache via `cache_cli.py`. No subcommand = `stats`. Resolve its path the same way as `$CLI` (swap `config_cli.py` → `cache_cli.py`), then run it:

```bash
CACHE="$(ls "${CLAUDE_PLUGIN_ROOT:-}/hooks/cache_cli.py" 2>/dev/null \
  || ls ~/.claude/plugins/cache/*/simple-tts/*/hooks/cache_cli.py 2>/dev/null | sort -V | tail -1 \
  || ls "$PWD/hooks/cache_cli.py" 2>/dev/null)"
python3 "$CACHE" stats
```

- `/tts cache` or `/tts cache stats` → run with `stats`: prints each cached phrase, its play count, last-used time and size, plus total size vs the `cache_max_mb` budget. Show the output to the user. Safe to add a TTS tag.
- `/tts cache prune` → run with `prune` (optionally `prune --max-mb N`): evicts least-used-then-oldest entries down to the budget and reports bytes freed.
- `/tts cache clear` → run with `clear`: deletes the whole cache. Confirm what was removed.

The size budget is the `cache_max_mb` config key (default 100). Eviction also runs automatically after each new synthesis.
