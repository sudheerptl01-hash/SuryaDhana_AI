#!/bin/bash
# Start the SuryaDhana stack automatically when you log in to this Mac (a per-user launchd agent), so a restart
# doesn't leave the terminal down and the morning jobs (08:45 gold, 08:50 note, 09:09 pre-open) un-run.
#
#   scripts/install_autostart.sh            install (or update) and start nothing now
#   scripts/install_autostart.sh --remove   uninstall
#
# It runs `UI_MODE=prod ./start-local.sh start` once at login; logs go to .logs/autostart.log. Nothing else changes:
# no root, no system files, only ~/Library/LaunchAgents/com.suryadhana.stack.plist.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.suryadhana.stack"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $PLIST"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/.logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>-lc</string><string>cd "$ROOT" &amp;&amp; sleep 20 &amp;&amp; UI_MODE=prod ./start-local.sh start</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$ROOT/.logs/autostart.log</string>
  <key>StandardErrorPath</key><string>$ROOT/.logs/autostart.log</string>
</dict>
</plist>
PL
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
echo "installed $PLIST: the stack will start ~20 s after your next login (log: .logs/autostart.log)"
echo "to start it now as well: UI_MODE=prod ./start-local.sh start"
