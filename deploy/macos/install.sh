#!/usr/bin/env bash
# Install the MiniX print server as a launchd user agent (no sudo). Idempotent.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.minixprint.server
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/Library/Logs/minixprint"

[ -x "$REPO/.venv/bin/minixprint" ] || { echo "missing $REPO/.venv/bin/minixprint (python3 -m venv .venv && .venv/bin/pip install -e .)" >&2; exit 1; }

mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$REPO/deploy/macos/$LABEL.plist" > "$DEST"
plutil -lint "$DEST" >/dev/null

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$DEST"
launchctl kickstart -k "gui/$UID/$LABEL"
echo "installed $LABEL; logs: $LOGS/server.log"
echo "remove with: launchctl bootout gui/$UID/$LABEL && rm $DEST"
