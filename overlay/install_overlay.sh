#!/bin/bash
# Instalator demona nakładki KITT (Knight Rider) dla simple-tts.
# Kopiuje overlay do stabilnej lokalizacji, instaluje zależności (PyObjC+Pillow)
# i zakłada LaunchAgent (autostart po zalogowaniu). Idempotentny.
#
# Użycie:  ./install_overlay.sh [ścieżka_do_python3]
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="$HOME/.claude/simple-tts-overlay"
PLIST="$HOME/Library/LaunchAgents/com.usterk.simple-tts-kitt.plist"
LABEL="com.usterk.simple-tts-kitt"

# 1) python3 z GUI: preferuj framework build z python.org, potem homebrew.
pick_python() {
  if [ "${1:-}" ]; then echo "$1"; return; fi
  for p in /usr/local/bin/python3 /opt/homebrew/bin/python3 python3; do
    command -v "$p" >/dev/null 2>&1 && { echo "$p"; return; }
  done
  echo python3
}
PY="$(pick_python "${1:-}")"
echo "Python: $PY"

# 2) zależności
echo "Instaluję zależności (PyObjC + Pillow)…"
"$PY" -m pip install --quiet --upgrade pyobjc-framework-Cocoa Pillow
"$PY" -c "import AppKit, PIL" || { echo "Brak AppKit/PIL po instalacji"; exit 1; }

# 3) kopia do stabilnej lokalizacji (przeżywa aktualizacje pluginu)
mkdir -p "$DEST_DIR"
cp "$SRC_DIR"/kitt_frame.py "$SRC_DIR"/kitt_state.py "$SRC_DIR"/kitt_overlay.py "$DEST_DIR"/
echo "Skopiowano do $DEST_DIR"

# 4) LaunchAgent
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DEST_DIR/kitt_overlay.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "LaunchAgent załadowany ($LABEL). Nakładka wstanie teraz i po każdym logowaniu."
echo "Wyłączenie animacji: /simple-tts:tts knight-rider off  (albo w configu knight_rider=false)."
