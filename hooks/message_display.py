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

# 24-bit truecolor; falls back to nearest colour on terminals without
# truecolor support. GREEN is used for the "ok" category AND for a tag with
# no category at all (today's neutral tag stays green for compatibility).
GREEN = "\x1b[38;2;0;100;0m"
FIREBRICK = "\x1b[38;2;178;34;34m"   # err — error/blocker
AMBER = "\x1b[38;2;204;136;0m"       # q — question/decision needed
RESET = "\x1b[0m"

TTS_TAG_RE = re.compile(
    r"[ \t]*<!--\s*TTS(?:\[(ok|err|q)\])?\s*:\s*(.*?)\s*-->[ \t]*",
    re.DOTALL | re.IGNORECASE)

CATEGORY_COLORS = {"ok": GREEN, "err": FIREBRICK, "q": AMBER}


def _mode():
    """Read the tag_display preference from config; default to styled."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from tts_utils import load_config
        return load_config().get("tag_display", "styled")
    except Exception:
        return "styled"


def render_tag(text, mode="styled"):
    """Rewrite every <!-- TTS[cat]: msg --> marker per `mode`; collapse msg
    whitespace. In styled mode the 🔊 line's colour depends on the category:
    ok/no category = green, err = firebrick, q = amber."""
    def repl(match):
        category = (match.group(1) or "").lower()
        msg = " ".join(match.group(2).split())
        if not msg or mode == "hidden":
            return ""
        if mode == "plain":
            return f"🔊 {msg}"
        color = CATEGORY_COLORS.get(category, GREEN)
        return f"{color}🔊 {msg}{RESET}"

    new = TTS_TAG_RE.sub(repl, text)
    if mode == "hidden" and new != text:
        new = new.rstrip()
    return new


def _find_text_with_marker(node):
    """Return the first string value (depth-first) that contains the marker."""
    if isinstance(node, str):
        return node if ("<!--" in node and "TTS" in node.upper()) else None
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
