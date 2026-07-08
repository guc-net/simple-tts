# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin that speaks short TTS summaries when Claude finishes a task or needs user attention. Uses Microsoft edge-tts neural voices by default (via `uvx`, online) with macOS `say` as the offline fallback. Distributed via the `usterk/simple` marketplace.

## Architecture

- **hooks/hooks.json** — auto-registers all hooks via `${CLAUDE_PLUGIN_ROOT}` when the plugin is enabled; no settings.json edits, no file copying
- **hooks/tts_utils.py** — shared module: config loading (`~/.claude/simple-tts-config.json`), phonetic sanitization, non-blocking `speak()`, transcript TTS tag extraction, voice→gender + gender→edge-voice mapping (`voice_gender`, `EDGE_VOICES`, `edge_voice_for`). Speech state (PID + timestamp of the running TTS process) lives in `~/.claude/simple-tts-state.json` under `flock`
- **hooks/edge_speak.py** — detached helper for the `edge` engine: synthesizes via `uvx edge-tts` (no install — runs out-of-process, plugin stays stdlib-only), plays the mp3 with `afplay`, and falls back to local `say` on any failure (offline, no `uvx`, timeout, empty result). Reads its payload from the `SIMPLE_TTS_PAYLOAD` env var (so text never appears in `ps`). Launched as its own process group so a priority interrupt kills synthesis + playback together via `os.killpg`. On a cache hit it plays straight from disk (skips synthesis); on a miss it synthesizes to a `.synthtmp-*.mp3` temp in the cache dir, `os.replace`s it into place (atomic), records usage and evicts. All cache logic lives in `audio_cache.py`. The `say` fallback is never cached. **Background sound** (`intro_sound` config, default `"kitt"`): when set, `_mix_kitt` ffmpeg-mixes the speech under `sounds/<name>.mp3` at *playback* — 1 s intro, sidechain-ducked bed, outro ending in the sound's quiet valley (KITT loops in ~1.28 s cycles; end = first valley at `0.04 + n·1.28` after intro+speech+0.35 s, with a 0.10 s fade to zero). Mix goes to a system temp mp3, played then unlinked; the on-disk **cache always holds the plain speech**, so the effect toggles instantly with config and never pollutes the cache. Missing ffmpeg/ffprobe or sound file, or any ffmpeg error → plain speech plays. A missing `intro_sound` key means off (production always passes it explicitly)
- **hooks/audio_cache.py** — the on-disk audio cache (used by edge_speak + cache_cli). Entries are `<sha256(engine,voice,rate,text)>.mp3` under `~/.claude/simple-tts-audio-cache/`; a flock-guarded `index.json` holds per-entry metadata (text, voice, rate, play count, created/last_used). **Eviction is size-based** (`cache_max_mb`, default 100): when total mp3 size exceeds the budget, entries are removed least-used-then-oldest (`(plays, last_used)` ascending), only as many as needed. Reconciles index↔disk (drops rows whose mp3 vanished; mp3s with no row count as plays=0 → evictable). `sweep_temp()` removes `.synthtmp-*` orphans older than `TMP_MAX_AGE`. API: `key_for`, `cache_path`, `record_store`, `record_hit`, `evict`, `stats`, `clear`, `sweep_temp`
- **hooks/cache_cli.py** — `python3 hooks/cache_cli.py stats|prune [--max-mb N]|clear`; backs `/tts cache`. `stats` prints each phrase with play count, last-used and size vs budget; `prune` evicts to budget; `clear` wipes the cache
- **hooks/stop_tts.py** — Stop hook (tag mode only): extracts `<!-- TTS: message -->` from `last_assistant_message` (preferred) or transcript fallback. No tag → silence (or `fallback_message` from config). Exits immediately when `speak_via == "tool"`
- **hooks/notification_tts.py** — Notification hook: speaks a short phrase in the configured language (`MESSAGES` catalog), naming the tool from permission messages when possible. Never reads transcript (avoids repeating stale messages)
- **hooks/session_start.py** — SessionStart hook: injects the TTS instruction as `additionalContext`, generated from config (language, voice gender → grammar forms, name). Two variants by `speak_via`: `tag` (append a hidden `<!-- TTS: -->` comment) or `tool` (call the `speak` MCP tool, no visible marker). Shared content rules via `content_rules()`. Replaces the old CLAUDE.md-append approach
- **hooks/message_display.py** — MessageDisplay hook (tag mode): rewrites the hidden `<!-- TTS: ... -->` marker in the on-screen display via `hookSpecificOutput.displayContent`. Display-only — the transcript keeps the marker so the Stop hook still speaks it. Default renders the spoken line as a green `🔊 <text>` (ANSI); config key `tag_display` switches it: `styled` (green speaker, default) / `plain` (🔊 line, no ANSI — fallback if a terminal mangles ANSI) / `hidden` (remove the marker entirely). Field-name-agnostic (the MessageDisplay stdin schema is undocumented): it locates the marker anywhere in the JSON; emits nothing when no marker is present. MessageDisplay fires per rendered chunk and the marker sits at the message end, so it is rewritten when the final chunk renders. Solves the visible-`<!-- TTS -->` problem (some Claude Code versions render HTML comments as raw text) without losing tag mode's deterministic speech
- **hooks/phonetics/<lang>.json** — phonetic dictionaries (English term → phonetic spelling); user overrides merge in from `~/.claude/simple-tts-phonetics.json`
- **hooks/speak_cli.py** — manual test mode: `python3 hooks/speak_cli.py "text"` speaks through the full pipeline, bypassing mute and quiet hours (`force=True`)
- **skills/tts/SKILL.md** — invoked as `/simple-tts:tts` (plugin skills are namespaced; a bare `/tts` needs a personal `~/.claude/commands/tts.md` wrapper). `on|off|status` toggles `"enabled"` in the config (mute without uninstalling); `cache [stats|prune|clear]` manages the audio cache via `cache_cli.py` (resolves the script path whether installed as a plugin or run from the repo). `cache stats` always leads with a 🔝 most-played section
- **mcp/server.py** + **.mcp.json** — stdlib-only MCP stdio server with a `speak` tool, for environments without hooks (Cowork, desktop chat) and for Claude Code `tool` mode. Reuses `tts_utils.speak()` (so mute + quiet hours apply); when to call it is governed by the SessionStart instruction, not the tool description
- **skills/simple-tts-setup/SKILL.md** — setup wizard (`/simple-tts-setup`): writes the config file, handles uninstall and migration from pre-2.0 installs
- **hooks/user_prompt.py** — UserPromptSubmit hook: marks "this session is working" for the overlay (per-session marker in `~/.claude/simple-tts-busy.d/`, `set_session_busy`) and clears the session's `attention` marker (user is back). The Stop hook clears both. Silent no-op without config; writes nothing to stdout so it adds no prompt context
- **hooks/attention_clear.py** — PostToolUse hook: a tool just ran, so any permission was granted — clears this session's `attention` marker. Fires on every tool call, so the fast path (no attention markers at all) exits after a single `listdir` without touching stdin. The `attention` marker itself is set by the Notification hook (`set_session_attention`, dir `~/.claude/simple-tts-attention.d/`) regardless of mute/quiet hours — the visual is independent of speech
- **overlay/** — the **status overlay** (optional GUI daemon, not on the hook path so the core stays stdlib-only). `kitt_state.py` (stdlib, unit-tested) aggregates simple-tts state across all sessions into `snapshot()`: mode **speak** (TTS PID alive + a real `afplay`/`say` process) > **attention** (fresh marker in `simple-tts-attention.d` — someone waits for the user; stale after 30 min) > **think** (fresh marker in `simple-tts-busy.d`; stale after 15 min) > **idle**, `None` when `knight_rider` is off; plus `busy` (how many sessions work in parallel) and `age` (oldest running work, seconds). `kitt_overlay.py` is the theme **host**: transparent, click-through, always-on-top Cocoa `NSPanel` per screen (`CanJoinAllSpaces` + `FullScreenAuxiliary`, exactly menu-bar height), fast/slow timers (after 60 s of continuous idle the panels fade, order out and only a 1 s state poll remains), speech-envelope reading and applying theme updates inside one `CATransaction`. The look itself lives in **overlay/themes/** — `base.py` defines the contract (`sprites()` PIL images → converted once to `CGImage`; `layers()` flat layer specs; `step()` per-frame `(idx, "op"|"pos"|"img", value)` updates with dirty-check, so an unchanged frame costs nothing) plus shared extras every theme gets for free: fleet pips (one dot per working session, up to 5, shown in think/attention) and `age_mult` (animations speed up the longer the oldest work runs). Themes: `kitt` (default; continuous LED sweep, afterglow tail, speech bloom), `cylon` (wider pure-red eye, sinusoidal sweep), `hal` (HAL 9000 breathing eye), `ekg` (scrolling heart-monitor trace, heart rate = activity), `matrix` (digital rain columns), `spark` (central cat-eye lens with a spark stream — pale sparks stream in from the left, converge, ordered green sparks fly out the right). Every theme implements all four modes; **attention** is always amber (blink pattern from `base.blink`). Selected via the `overlay_theme` config key, switchable live — the host rebuilds layers without restart. `kitt_frame.py` keeps the KITT sprite drawing (used by the kitt/cylon themes). Deps (pyobjc Cocoa+Quartz + Pillow) and autostart via `install_overlay.sh` (copies overlay + themes to `~/.claude/simple-tts-overlay/`, writes a LaunchAgent); `uninstall_overlay.sh` reverses it
- **.claude-plugin/plugin.json** — plugin manifest (version auto-bumped by CI)

## Key design decisions

- **Speech engine** (`"engine"` config key, default `"edge"`): `edge` uses Microsoft edge-tts neural voices (online, high quality) with the local `say` voice as automatic fallback; `say` uses the local macOS voice only. The edge voice is **derived at runtime** from `voice_gender(config["voice"])` + language via `EDGE_VOICES` — there is no stored edge-voice field, so it auto-adapts per machine (Krzysztof→Marek, Ewa→Zofia). Defaulting `engine` to `edge` in `DEFAULT_CONFIG` means existing installs pick it up on update via the `load_config()` merge — no migration code. The local `voice`/`rate` keys stay as the `say` fallback; `edge_rate` (percent) tunes edge speed separately
- All hooks are silent no-ops when `~/.claude/simple-tts-config.json` doesn't exist — enabling the plugin without running setup does nothing
- `speak()` detaches the TTS process (`Popen` + `start_new_session`) so hooks return immediately and the 5 s hook timeout never cuts speech off. For `edge` it spawns `edge_speak.py` (which itself does synth → play → `say` fallback); for `say` it spawns `say` directly. Either way the caller never waits for audio — fire-and-forget
- Notification hook speaks with `priority=True`: it kills the plugin's own running TTS process group (`_is_our_tts` checks the PID's command — a `say` process or the `edge_speak.py` helper — never other apps' `say`). The Stop hook stays silent while a previous speech is playing or <2 s old
- Stop hook only speaks when a `<!-- TTS: -->` tag exists — silence means Claude stopped for a permission prompt, and the notification hook handles that
- Phonetic replacement is whole-word, longest-match-first (so `deployed` doesn't get mangled by the `deploy` entry)
- `speak()` honors `"enabled": false` (mute) and `"quiet_hours"` (`{"start","end"}`, may wrap past midnight; malformed config fails open — speech stays on). `force=True` bypasses both (used only by speak_cli)
- **Knight Rider mode** (`"knight_rider"` config key, default `true`) is one switch for two effects: the KITT siren bed under the voice (gates `intro_sound` in the edge payload — off ⇒ `"none"`) and the status overlay (`kitt_state.overlay_enabled`). Toggle via `/simple-tts:tts knight-rider on|off`; the overlay's look is a separate key `"overlay_theme"` (default `"kitt"`, `/simple-tts:tts theme <name>`, unknown names fall back to kitt). The overlay is a separate daemon with its own deps, so muting speech (`enabled:false`) does not hide the overlay and vice-versa — the visual is governed only by `knight_rider`
- **Attention mode**: the Notification hook marks "session waits for the user", the overlay blinks amber until the user reacts. Cleared by whichever comes first: a new prompt (UserPromptSubmit), a tool executing (PostToolUse — permission was granted mid-turn) or the turn ending (Stop). Markers go stale after 30 min so an orphaned marker (killed session) cannot blink forever

## Tests & lint

`tests/` (pytest) covers tag extraction, sanitizer, speak() dedup/priority, mute, quiet hours and the hook message catalogs; `conftest.py` redirects all `~/.claude` paths into tmp and fakes `subprocess.Popen`, so tests never speak or touch real config. Ruff config in `pyproject.toml`. Run locally:

```bash
uvx --with pytest pytest tests/ -q
uvx ruff check .
```

Both run in CI (`.github/workflows/test.yml`) on every push and PR.

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
