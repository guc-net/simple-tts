#!/usr/bin/env python3
"""
Minimal MCP stdio server exposing a `speak` tool backed by macOS `say`.

Makes simple-tts work outside Claude Code hooks — in Claude Cowork and the
Claude desktop app (regular chat), where hooks don't fire but local MCP
servers run on the host. Pure stdlib, newline-delimited JSON-RPC.

Claude Code / Cowork: registered automatically via the plugin's .mcp.json.
Claude desktop app: add to claude_desktop_config.json (see README).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hooks'))
from tts_utils import load_config, speak

PROTOCOL_VERSION = "2025-06-18"

SPEAK_TOOL = {
    "name": "speak",
    "description": (
        "Speak a short summary aloud to the user via macOS text-to-speech. "
        "Call this at the END of your response when you have completed a task "
        "(say what you did) or when you need the user's input or attention "
        "(say what you need). The user may be away from the screen — this is "
        "how they know to come back. Max 10 words, natural spoken language, "
        "in the user's configured TTS language, specific to what happened — "
        "never generic. Avoid acronyms and foreign jargon; describe instead. "
        "Only call when your session instructions tell you to use this tool: "
        "in tag mode the <!-- TTS: --> comment already speaks, so calling here "
        "would double-speak."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Short spoken-language summary (max 10 words)",
            },
            "priority": {
                "type": "boolean",
                "description": "Interrupt any ongoing speech (use when user attention is needed)",
                "default": False,
            },
        },
        "required": ["message"],
    },
}


def handle(req):
    method = req.get("method")
    if method == "initialize":
        return {
            "protocolVersion": req.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "simple-tts", "version": "2.0.0"},
        }
    if method == "tools/list":
        return {"tools": [SPEAK_TOOL]}
    if method == "tools/call":
        params = req.get("params", {})
        if params.get("name") != "speak":
            raise ValueError(f"Unknown tool: {params.get('name')}")
        args = params.get("arguments", {})
        message = str(args.get("message", "")).strip()
        if not message:
            raise ValueError("message is required")
        if load_config() is None:
            return {"content": [{"type": "text", "text":
                    "simple-tts is not configured — run /simple-tts-setup in Claude Code first."}],
                    "isError": True}
        speak(message, priority=bool(args.get("priority", False)))
        return {"content": [{"type": "text", "text": "Spoken."}]}
    if method == "ping":
        return {}
    raise ValueError(f"Unknown method: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:
            continue  # notification (e.g. notifications/initialized) — no response
        resp = {"jsonrpc": "2.0", "id": req["id"]}
        try:
            resp["result"] = handle(req)
        except Exception as e:
            resp["error"] = {"code": -32603, "message": str(e)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == '__main__':
    main()
