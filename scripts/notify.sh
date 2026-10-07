#!/usr/bin/env bash
# Send a task-completion notice to the owner through Hermes (bot "cody") on Telegram DM.
# Usage: scripts/notify.sh "T17 merged: ..."   (message text may also come from stdin)
set -euo pipefail
TARGET="${REALM_NOTIFY_TARGET:-telegram:Teeradet Wichai (dm)}"
exec "$HOME/.local/bin/hermes" send --to "$TARGET" "$@"
