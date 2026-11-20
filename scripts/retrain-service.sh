#!/bin/sh
# Run scripts/retrain.sh every day at 04:30 under launchd (if the Mac is asleep then, it runs on
# wake), so the website's model keeps up with the crawler.
#
#   scripts/retrain-service.sh install     schedule it
#   scripts/retrain-service.sh uninstall   stop and remove
#   scripts/retrain-service.sh status      last run
#   scripts/retrain-service.sh run         run it now (in the background, logged)
#   scripts/retrain-service.sh log         follow the log
set -eu

LABEL=com.mira.retrain
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mira-retrain.log"
REPO=$(cd "$(dirname "$0")/.." && pwd)
UV=$(command -v uv || echo "$HOME/.local/bin/uv")

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
  <array><string>/bin/sh</string><string>$REPO/scripts/retrain.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>PATH</key><string>$(dirname "$UV"):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  sleep 1
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Installed $LABEL (daily 04:30); log: $LOG"
  ;;
uninstall)
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  ;;
status)
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|last exit" || echo "not installed"
  grep -E "deployed|nothing to deploy|not deploying|failed" "$LOG" 2>/dev/null | tail -3 || true
  ;;
run)
  launchctl kickstart "gui/$(id -u)/$LABEL" && echo "Started; follow with: $0 log"
  ;;
log)
  tail -f "$LOG"
  ;;
*)
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
