#!/usr/bin/env python3
"""
MessageDisplay hook for simple-tts (tag mode).

In tag mode Claude appends a hidden `<!-- TTS: ... -->` comment that the Stop
hook reads aloud. Some Claude Code versions render that comment as visible text
in the console. This hook redacts the marker from what is DISPLAYED via
`hookSpecificOutput.displayContent` — a display-only change, so the transcript
(which the Stop hook reads) keeps the original marker and speech still works.

The MessageDisplay stdin schema is undocumented, so this hook is field-name-
agnostic: it locates the marker anywhere in the JSON and returns the cleaned
text. If no marker is present it emits nothing (no display change).
"""

import json
import re
import sys

# Matches our marker plus the surrounding blank line it usually sits on.
TTS_TAG_RE = re.compile(r"[ \t]*<!--\s*TTS:.*?-->[ \t]*\n?", re.DOTALL | re.IGNORECASE)


def strip_tag(text):
    """Remove every <!-- TTS: ... --> marker and any blank line left behind."""
    cleaned = TTS_TAG_RE.sub("", text)
    if cleaned == text:
        return text
    return cleaned.rstrip()


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

    cleaned = strip_tag(text)
    if cleaned == text:
        return

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "MessageDisplay",
        "displayContent": cleaned,
    }}))


if __name__ == "__main__":
    main()
