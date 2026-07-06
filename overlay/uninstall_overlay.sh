#!/bin/bash
# Odinstalowuje demona nakładki KITT: wyładowuje LaunchAgent i usuwa pliki.
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.usterk.simple-tts-kitt.plist"
DEST_DIR="$HOME/.claude/simple-tts-overlay"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
pkill -f "simple-tts-overlay/kitt_overlay.py" 2>/dev/null || true
rm -rf "$DEST_DIR"
echo "Nakładka KITT odinstalowana (LaunchAgent usunięty, proces zatrzymany)."
