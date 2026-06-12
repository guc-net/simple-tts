---
description: "Interactive setup wizard for simple-tts plugin. Configures macOS text-to-speech notifications for Claude Code. Also handles uninstall and migration from pre-2.0 installs."
user_invocable: true
---

# Simple TTS Setup

You are running an interactive setup wizard for the **simple-tts** plugin. Guide the user through configuration step by step, proposing sensible defaults they can accept with Enter.

The plugin's hooks auto-register via the plugin's `hooks/hooks.json` — setup only needs to write the config file. No settings.json edits, no file copying, no CLAUDE.md changes. Hooks stay silent until the config file exists, so an enabled-but-unconfigured plugin does nothing.

IMPORTANT: Gather ALL choices first, then apply everything at once. Do NOT stop between questions to wait — ask all questions in a single response, each on its own line. The user will answer all at once or press Enter to accept defaults.

## Step 1: Platform check

```bash
uname -s
```

If NOT `Darwin`:
> This plugin requires **macOS** (uses the system `say` command). It won't work on your system.

Stop here.

## Step 2: Migration check (pre-2.0 installs)

Check for leftovers from the old installation method:

```bash
ls ~/.claude/hooks/simple-tts 2>/dev/null
grep -l "simple-tts" ~/.claude/settings.json 2>/dev/null
grep -l "<!-- TTS:" ~/.claude/CLAUDE.md 2>/dev/null
```

If any are found, tell the user:
> Found leftovers from an older simple-tts install. Since v2.0 hooks auto-register with the plugin and the TTS instruction is injected per-session — these are no longer needed and would cause duplicate speech:
> - `~/.claude/hooks/simple-tts/` (old wrapper)
> - `simple-tts` hook entries in `~/.claude/settings.json`
> - TTS instruction block in `~/.claude/CLAUDE.md`
>
> Remove them? [yes]

On confirmation:
- Delete `~/.claude/hooks/simple-tts/`
- Remove hook entries whose command contains `simple-tts` from `~/.claude/settings.json` (and from project `.claude/settings.json` if present). Preserve all other hooks.
- Remove the TTS instruction block from `~/.claude/CLAUDE.md` (and project `CLAUDE.md` if present). The block starts with `- Add \`<!-- TTS:` and ends before the next line starting with `- ` at the same indent level (or end of file). Only remove the TTS block, nothing else.
- Delete `~/.claude/simple-tts-last-speak` (replaced by `simple-tts-state.json`)

## Step 3: Check if already configured

Read `~/.claude/simple-tts-config.json` if it exists. If it does, show current config and ask:

> Simple TTS is already configured:
> - Voice: **{voice}**
> - Name: **{name}** (or: not set)
>
> What would you like to do?
> 1. Reconfigure
> 2. Uninstall
> 3. Cancel

If user picks uninstall → go to **Uninstall** section below.
If user picks cancel → stop.
Otherwise continue with reconfiguration.

If not yet configured, proceed to step 4.

## Step 4: Detect available voices

```bash
say -v '?' 2>/dev/null
```

Group voices by language. Detect the user's system language from the `LANG` environment variable (e.g. `pl_PL` → Polish, `en_US` → English, `de_DE` → German). Use that as the default language.

Present ALL questions at once:

> **Simple TTS Setup**
>
> Available voices on your system:
> {show voices grouped by language, highlight the detected default language}
>
> Please answer these questions (press Enter to accept defaults):
>
> 1. **Language** [**{detected, e.g. Polish}**]: _language for TTS messages_
> 2. **Voice** [**{best voice for chosen language}**]: _which voice to use?_
> 3. **Speed** [**220**]: _words per minute (200=normal, 220=slightly faster, 300=fast)_
> 4. **Your name** [**skip**]: _optional — Claude will sometimes greet you by name (~30% of messages)_
> 5. **Fallback message** [**skip**]: _optional — short phrase spoken when a response has no TTS tag (e.g. "Done"); default is silence_
> 6. **Quiet hours** [**skip**]: _optional — time window when speech is silenced, e.g. 22:00-07:00_
> 7. **Preview?** [**no**]: _say "yes" to hear a sample with your chosen settings_

Default voice per language (pick the highest quality available):
- Polish: Krzysztof (Enhanced) or Ewa (Premium)
- English: Samantha (Enhanced) or Daniel
- German: Anna (Enhanced)
- French: Thomas (Enhanced)
- For other languages, pick the first Enhanced/Premium voice available

Wait for the user's single response.

**Validate the chosen voice** against the `say -v '?'` output from this step: the chosen name must match an installed voice (compare the base name, ignoring quality suffixes like "(Enhanced)"). If it doesn't, list the closest matches for the chosen language and ask again — never write an unverified voice into the config, a typo would silence the plugin with no error.

## Step 5: Preview (if requested)

If the user said "yes" to preview, run:
```bash
say -v "<voice>" -r <rate> "This is how I will sound. Testing one two three."
```
Use a sentence in the chosen language. After preview, ask: "Sound good? (Enter=yes, or adjust voice/speed)"
If user wants changes, go back to questions.

## Step 6: Save config

Write `~/.claude/simple-tts-config.json`:
```json
{
  "voice": "<chosen>",
  "rate": <chosen rate, default 220>,
  "language": "<chosen language, e.g. Polish>",
  "name": "<name or empty string>",
  "name_chance": 0.3
}
```

Optional keys (add only if the user chose them):
- `"fallback_message"`: phrase spoken when a response has no TTS tag
- `"quiet_hours"`: `{"start": "22:00", "end": "07:00"}` — no speech inside this window (may wrap past midnight)
- `"enabled"`: `false` mutes all speech without uninstalling (toggled by `/tts on|off`; missing = enabled)
- `"debug"`: `true` to log notification payloads to `~/.claude/simple-tts-notification-debug.log` (auto-trimmed to 200 lines)

That's all — hooks are auto-registered by the plugin, and the TTS instruction is injected into each session by the SessionStart hook based on this config (language, voice gender for grammar forms, name).

## Step 7: Test and done

```bash
say -v "<voice>" -r <rate> "Setup complete!"
```

> **Simple TTS configured!**
>
> From the next session, Claude will speak short summaries when:
> - finishing a task
> - needing your attention
>
> To mute/unmute without uninstalling: `/tts off`, `/tts on`
> To reconfigure: `/simple-tts-setup`
> To uninstall: `/simple-tts-setup` → Uninstall
>
> Custom pronunciations: create `~/.claude/simple-tts-phonetics.json` with `{"term": "phonetic spelling"}` entries — they override the built-in dictionary.
> Test speech from a terminal (bypasses mute and quiet hours): `python3 hooks/speak_cli.py "your text"` from the plugin directory.

---

## Uninstall

1. Remove `~/.claude/simple-tts-config.json` and `~/.claude/simple-tts-state.json` — hooks go silent immediately.
2. Run the migration check from Step 2 and clean any pre-2.0 leftovers too.
3. Tell user:
> Simple TTS removed.
> To fully disable the hooks as well: `claude plugin disable simple-tts`
> To set up again: `/simple-tts-setup`
