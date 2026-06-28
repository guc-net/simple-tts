"""The MCP server must start from .mcp.json in BOTH launch contexts:

- plugin context  — Claude Code text-substitutes the literal ${CLAUDE_PLUGIN_ROOT}
  token in the args with the plugin's install dir (it does NOT export an env
  var), then runs the command from an arbitrary cwd;
- project context — the repo's .mcp.json is auto-loaded with the token left
  unsubstituted, and cwd is the repo root.

These two tests replay exactly what Claude Code does, so they catch path-
resolution regressions (e.g. relying on $CLAUDE_PLUGIN_ROOT as an env var, or a
bare relative path) that unit tests on the source never would.
"""

import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = (b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        b'{"protocolVersion":"2024-11-05","capabilities":{},'
        b'"clientInfo":{"name":"t","version":"1"}}}\n')


def _spec():
    with open(os.path.join(ROOT, ".mcp.json")) as f:
        return json.load(f)["mcpServers"]["simple-tts"]


def _clean_env():
    # Claude Code does not export CLAUDE_PLUGIN_ROOT; make sure we don't either.
    return {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}


def _initializes(argv, cwd):
    p = subprocess.run(argv, input=INIT, capture_output=True, cwd=cwd, timeout=30)
    assert b'"serverInfo"' in p.stdout and b'simple-tts' in p.stdout, \
        p.stderr.decode(errors="replace")


def test_plugin_context_substituted_token(tmp_path):
    """Token replaced with the install dir; cwd is arbitrary (must be ignored)."""
    spec = _spec()
    argv = [spec["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", ROOT)
                                for a in spec["args"]]
    env = _clean_env()
    p = subprocess.run(argv, input=INIT, capture_output=True,
                       cwd=str(tmp_path), env=env, timeout=30)
    assert b'"serverInfo"' in p.stdout, p.stderr.decode(errors="replace")


def test_project_context_literal_token():
    """Token left literal; resolves against the repo root via $PWD fallback."""
    spec = _spec()
    argv = [spec["command"]] + spec["args"]
    p = subprocess.run(argv, input=INIT, capture_output=True,
                       cwd=ROOT, env=_clean_env(), timeout=30)
    assert b'"serverInfo"' in p.stdout, p.stderr.decode(errors="replace")
