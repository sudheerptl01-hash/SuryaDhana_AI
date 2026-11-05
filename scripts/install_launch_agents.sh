#!/bin/bash
# Install / inspect / remove the SuryaDhana LaunchAgents (ops/launchd/):
#   com.suryadhana.watchdog — starts the core stack at login and every 2 min restarts what died
#   com.suryadhana.awake    — keeps the Mac mini awake while logged in (caffeinate -s -i)
#
#   scripts/install_launch_agents.sh install | status | uninstall
#
# Per-user agents: they run once you are logged in. With FileVault ON, a reboot waits at the unlock
# screen until someone logs in — nothing local can run before that; HEALTHCHECK_PING_URL (see
# scripts/stack_watchdog.sh) is how you hear about it from off the machine.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
AGENTS="com.suryadhana.awake com.suryadhana.watchdog"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    mkdir -p "$DEST" "$ROOT/.logs"
    chmod +x "$ROOT/scripts/stack_watchdog.sh"
    for a in $AGENTS; do
      sed "s#__ROOT__#$ROOT#g" "$ROOT/ops/launchd/$a.plist" > "$DEST/$a.plist"
      plutil -lint "$DEST/$a.plist" > /dev/null
      launchctl bootout "$DOMAIN/$a" 2> /dev/null || true          # idempotent re-install
      launchctl bootstrap "$DOMAIN" "$DEST/$a.plist"
      echo "installed $a"
    done
    ;;
  uninstall)
    for a in $AGENTS; do
      launchctl bootout "$DOMAIN/$a" 2> /dev/null || true
      rm -f "$DEST/$a.plist"
      echo "removed $a"
    done
    ;;
  status)
    for a in $AGENTS; do
      if launchctl print "$DOMAIN/$a" > /dev/null 2>&1; then
        state=$(launchctl print "$DOMAIN/$a" | awk -F'= ' '/^\tstate/ {print $2; exit}')
        echo "$a: loaded (${state:-?})"
      else
        echo "$a: not installed"
      fi
    done
    pmset -g assertions 2>/dev/null | grep -i "caffeinate" | head -2 || true
    ;;
  *) echo "usage: $0 install | status | uninstall" >&2; exit 2 ;;
esac
