#!/bin/sh
# Run `mira crawl --watch` as a macOS background job (launchd) that starts at login,
# restarts if it exits, and recrawls each Masters player before their 25-game log turns over.
#
#   scripts/crawl-service.sh install     start now and at every login
#   scripts/crawl-service.sh uninstall   stop and remove
#   scripts/crawl-service.sh status      is it running?
#   scripts/crawl-service.sh log         follow the log
#
# The Mac must be awake and on a network whose public IP is on the API key's whitelist.
set -eu

LABEL=com.mira.crawl
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mira-crawl.log"
REPO=$(cd "$(dirname "$0")/.." && pwd)
UV=$(command -v uv || echo "$HOME/.local/bin/uv")
RATE=${MIRA_RATE:-30}
WORKERS=${MIRA_WORKERS:-24}

case "${1:-}" in
install)
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>mira</string><string>crawl</string>
    <string>--watch</string><string>--rate</string><string>$RATE</string>
    <string>--workers</string><string>$WORKERS</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>PATH</key><string>$(dirname "$UV"):/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- After a crash or a 403 (e.g. a new IP), wait 5 minutes before retrying. -->
  <key>ThrottleInterval</key><integer>300</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Installed $LABEL; log: $LOG"
  ;;
uninstall)
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  ;;
status)
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|pid|last exit" || echo "not installed"
  ;;
log)
  tail -f "$LOG"
  ;;
*)
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
