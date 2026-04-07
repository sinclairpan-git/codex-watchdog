#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_TEMPLATE="$REPO_ROOT/config/examples/com.openclaw.watchdog.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/com.openclaw.watchdog.plist"
LOG_DIR="$HOME/Library/Logs"

mkdir -p "$TARGET_DIR" "$LOG_DIR"

sed \
  -e "s#__REPO_ROOT__#$REPO_ROOT#g" \
  -e "s#__HOME__#$HOME#g" \
  "$PLIST_TEMPLATE" > "$TARGET_PLIST"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
launchctl kickstart -k "gui/$(id -u)/com.openclaw.watchdog"

printf 'installed %s\n' "$TARGET_PLIST"
