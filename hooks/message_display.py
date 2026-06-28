#!/usr/bin/env python3
"""
MessageDisplay hook for simple-tts (tag mode).

In tag mode Claude appends a hidden `<!-- TTS: ... -->` comment that the Stop
hook reads aloud. Some Claude Code versions render that comment as visible raw
text. This hook rewrites the marker in what is DISPLAYED via
`hookSpecificOutput.displayContent` — a display-only change, so the transcript
(which the Stop hook reads) keeps the original marker and speech still works.

By default the marker is shown as a tidy green speaker line (`🔊 <text>`); the
`tag_display` config key switches this:
- "styled" (default): green 🔊 line (ANSI colour)
- "plain":            🔊 line, no ANSI (use if a terminal mangles ANSI)
- "hidden":           remove the marker entirely

The MessageDisplay stdin schema is undocumented, so this hook is field-name-
agnostic: it locates the marker anywhere in the JSON. MessageDisplay fires per
rendered chunk; our marker sits at the end of the message, so it is rewritten
when that final chunk renders.
"""

import json
import os
import re
import sys

GREEN = "\x1b[32m"
RESET = "\x1b[0m"

TTS_TAG_RE = re.compile(r"[ \t]*<!--\s*TTS:\s*(.*?)\s*-->[ \t]*", re.DOTALL | re.IGNORECASE)


def _mode():
    """Read the tag_display preference from config; default to styled."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tts_utils import load_config
        return load_config().get("tag_display", "styled")
    except Exception:
        return "styled"


def render_tag(text, mode="styled"):
    """Rewrite every <!-- TTS: msg --> marker per `mode`; collapse msg whitespace."""
    def repl(match):
        msg = " ".join(match.group(1).split())
        if not msg or mode == "hidden":
            return ""
        if mode == "plain":
            return f"🔊 {msg}"
        return f"{GREEN}🔊 {msg}{RESET}"

    new = TTS_TAG_RE.sub(repl, text)
    if mode == "hidden" and new != text:
        new = new.rstrip()
    return new


def _find_text_with_marker(node):
    """Return the first string value (depth-first) that contains the marker."""
    if isinstance(node, str):
        return node if "<!--" in node and "TTS:" in node.upper() else None
    if isinstance(node, dict):
        for value in node.values():
            found = _find_text_with_marker(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_text_with_marker(value)
            if found is not None:
                return found
    return None


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return

    text = _find_text_with_marker(data)
    if text is None:
        return  # no marker on screen → leave the display untouched

    new = render_tag(text, _mode())
    if new == text:
        return

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "MessageDisplay",
        "displayContent": new,
    }}))


if __name__ == "__main__":
    main()
