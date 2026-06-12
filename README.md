# simple-tts

A [Claude Code](https://claude.ai/code) plugin that speaks short contextual summaries using macOS text-to-speech when Claude finishes a task or needs your attention.

Instead of switching to your terminal to check what Claude did, you just hear it: *"Fixed the auth module as requested"* or *"Need your approval to run migration"*.

> **Requires macOS** — uses the built-in `say` command.

## Installation

```bash
# 1. Add marketplace
/plugin marketplace add usterk/simple

# 2. Install plugin
/plugin install simple-tts@simple

# 3. Run setup wizard
/simple-tts-setup
```

The setup wizard will guide you through:
- Choosing a TTS voice (any voice available on your macOS)
- Setting your name for personalized greetings (optional, ~30% of messages)
- Optional fallback phrase for responses without a TTS tag
- Testing the voice

Setup only writes a config file — hooks register automatically with the plugin, and the TTS instruction is injected into each session. Disabling the plugin disables everything.

To update:
```bash
/plugin update simple-tts@simple
```

## How it works

1. A **SessionStart** hook injects an instruction telling Claude to include a hidden `<!-- TTS: short summary -->` tag at the end of each response — generated from your config (language, voice gender for grammar forms, name), so changing the config changes the instruction immediately
2. When Claude **stops**, a hook extracts the tag and speaks it via macOS `say` (detached — never delays Claude)
3. When Claude **needs your attention** (permission prompt, waiting for input), a notification hook speaks a short phrase in your configured language, naming the tool when known (*"Potrzebuję zgody na narzędzie Bash"*)
4. Foreign terms are automatically sanitized for the chosen voice — acronyms get spelled out (`API` → `A P I`), common English words get phonetic equivalents

### Examples

What Claude writes in the response (invisible to the user):

```html
<!-- TTS: Fixed the parser according to your guidelines -->
<!-- TTS: Found a bug in the auth module -->
<!-- TTS: Tests pass, can I commit? -->
<!-- TTS: Need your approval to run the deploy script -->
```

What you hear when you're in another window:

> *"Fixed the parser according to your guidelines"*

or sometimes:

> *"Sarah, found a bug in the auth module"*

## Available voices

Run `say -v '?'` to see all voices on your system. The setup wizard will show voices for your locale. Some examples:

| Voice | Language | Quality |
|-------|----------|---------|
| Samantha | English (US) | Enhanced |
| Daniel | English (UK) | Enhanced |
| Krzysztof | Polish | Enhanced |
| Ewa | Polish | Premium |
| Thomas | French | Enhanced |
| Anna | German | Enhanced |

## Commands

| Command | Description |
|---------|-------------|
| `/simple-tts-setup` | Interactive setup / reconfigure / uninstall |
| `/tts on` / `/tts off` | Unmute / mute speech without uninstalling |
| `/tts status` | Show current config (enabled, voice, quiet hours) |

## Configuration

Stored in `~/.claude/simple-tts-config.json`:

```json
{
  "voice": "Samantha",
  "rate": 220,
  "language": "English",
  "name": "Sarah",
  "name_chance": 0.3
}
```

Optional keys:

| Key | Effect |
|-----|--------|
| `"fallback_message"` | Phrase spoken when a response has no TTS tag (default: silence) |
| `"enabled"` | `false` mutes all speech; toggled by `/tts on\|off` (missing = enabled) |
| `"quiet_hours"` | `{"start": "22:00", "end": "07:00"}` — no speech inside this window (may wrap past midnight) |
| `"debug"` | `true` logs notification payloads to `~/.claude/simple-tts-notification-debug.log` (trimmed to 200 lines) |

Deleting the config file silences the plugin without uninstalling it.

To test your configuration and pronunciations from a terminal (speaks even when muted or in quiet hours):

```bash
python3 hooks/speak_cli.py "deployed to production"
```

## Phonetic sanitization

The plugin includes a sanitizer that makes technical terms pronounceable by non-English TTS voices:

| Original | Sanitized |
|----------|-----------|
| `API` | `A P I` (spelled out) |
| `GOPATH` | `G O P A T H` |
| `cache` | `kesz` |
| `docker` | `doker` |
| `kubernetes` | `kubernetis` |
| `webhook` | `łebhuk` |

Built-in dictionaries live in `hooks/phonetics/<lang>.json`. To add or override pronunciations, create `~/.claude/simple-tts-phonetics.json` — its entries win over the built-ins:

```json
{
  "terraform": "teraform",
  "vault": "wolt"
}
```

## Beyond Claude Code: Cowork and the desktop app

Hooks only fire in the Claude Code CLI, so the plugin also ships an MCP server (`mcp/server.py`) exposing a `speak` tool:

- **Claude Cowork** — the plugin's MCP server registers automatically (via `.mcp.json`) and runs on your Mac, so it can use `say` even though Cowork sessions run in a VM. The tool's description tells Claude to call it when finishing a task or needing your attention.
- **Claude desktop app (regular chat)** — add the server to `~/Library/Application Support/Claude/claude_desktop_config.json`:

  ```json
  {
    "mcpServers": {
      "simple-tts": {
        "command": "bash",
        "args": ["-lc", "exec python3 \"$(find ~/.claude/plugins -path '*/simple-tts/*/mcp/server.py' 2>/dev/null | sort -V | tail -1)\""]
      }
    }
  }
  ```

  The `find` indirection always launches the latest installed plugin version. For more reliable end-of-response speech in chat, add to your Claude preferences: *"At the end of each response, call the simple-tts speak tool with a short summary."*
- **claude.ai in the browser** — not supported: web chat can only use remote connectors and cannot run local commands.

In Claude Code itself the `speak` tool is unnecessary — the session instruction tells Claude to use the TTS tag and never call the tool there, so they don't double-speak.

## Upgrading from 1.x

Version 2.0 registers hooks via the plugin itself and injects the TTS instruction per session. Run `/simple-tts-setup` once after updating — it detects and removes the old wrapper in `~/.claude/hooks/simple-tts/`, the hook entries in `settings.json`, and the instruction block in `CLAUDE.md`.

## Local development

```bash
claude --plugin-dir ./simple-tts
```

Tests and lint (run in CI on every push and PR):

```bash
pip install pytest ruff   # or use uvx
pytest tests/ -q
ruff check .
```

## License

MIT
