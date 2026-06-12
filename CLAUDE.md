# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin that uses macOS `say` to speak short TTS summaries when Claude finishes a task or needs user attention. Distributed via the `usterk/simple` marketplace.

## Architecture

- **hooks/hooks.json** — auto-registers all hooks via `${CLAUDE_PLUGIN_ROOT}` when the plugin is enabled; no settings.json edits, no file copying
- **hooks/tts_utils.py** — shared module: config loading (`~/.claude/simple-tts-config.json`), phonetic sanitization, non-blocking `speak()`, transcript TTS tag extraction. Speech state (PID + timestamp of the running `say`) lives in `~/.claude/simple-tts-state.json` under `flock`
- **hooks/stop_tts.py** — Stop hook: extracts `<!-- TTS: message -->` from `last_assistant_message` (preferred) or transcript fallback. No tag → silence (or `fallback_message` from config)
- **hooks/notification_tts.py** — Notification hook: speaks a short phrase in the configured language (`MESSAGES` catalog), naming the tool from permission messages when possible. Never reads transcript (avoids repeating stale messages)
- **hooks/session_start.py** — SessionStart hook: injects the TTS-tag instruction as `additionalContext`, generated from config (language, voice gender → grammar forms, name). Replaces the old CLAUDE.md-append approach
- **hooks/phonetics/<lang>.json** — phonetic dictionaries (English term → phonetic spelling); user overrides merge in from `~/.claude/simple-tts-phonetics.json`
- **mcp/server.py** + **.mcp.json** — stdlib-only MCP stdio server with a `speak` tool, for environments without hooks (Cowork, desktop chat). Reuses `tts_utils.speak()`; the SessionStart instruction forbids calling it in Claude Code (tag handles speech there)
- **skills/simple-tts-setup/SKILL.md** — setup wizard (`/simple-tts-setup`): writes the config file, handles uninstall and migration from pre-2.0 installs
- **.claude-plugin/plugin.json** — plugin manifest (version auto-bumped by CI)

## Key design decisions

- All hooks are silent no-ops when `~/.claude/simple-tts-config.json` doesn't exist — enabling the plugin without running setup does nothing
- `speak()` detaches `say` (`Popen` + `start_new_session`) so hooks return immediately and the 5 s hook timeout never cuts speech off
- Notification hook speaks with `priority=True`: it kills the plugin's own running `say` (PID checked against process name — never other apps' `say`). The Stop hook stays silent while a previous speech is playing or <2 s old
- Stop hook only speaks when a `<!-- TTS: -->` tag exists — silence means Claude stopped for a permission prompt, and the notification hook handles that
- Phonetic replacement is whole-word, longest-match-first (so `deployed` doesn't get mangled by the `deploy` entry)

## CI/CD

Every push to `main` triggers `.github/workflows/bump-version.yml`:
1. Determines bump type from commit message prefix: `feat:` → minor, `feat!:`/`breaking` → major, everything else → patch
2. Bumps version in `plugin.json`, commits with `[skip ci]`, creates git tag
3. Sends `repository_dispatch` to `usterk/simple` marketplace to update version and `ref`

**Commit message conventions**: prefix with `feat:` for minor bump, `feat!:` or `breaking` for major. No prefix = patch.

## Local testing

```bash
claude --plugin-dir .
```

Quick manual checks (no Claude session needed):

```bash
python3 hooks/session_start.py                      # prints additionalContext JSON
python3 -c "import sys; sys.path.insert(0,'hooks'); from tts_utils import sanitize_for_tts; print(sanitize_for_tts('deployed API cache', 'pl'))"
echo '{"message":"Claude needs your permission to use Bash"}' | python3 hooks/notification_tts.py   # speaks!
