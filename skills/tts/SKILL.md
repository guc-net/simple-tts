---
description: "Mute or unmute simple-tts speech without uninstalling. Usage: /tts on, /tts off, /tts status. Edits the enabled flag in the plugin config."
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
