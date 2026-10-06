#!/usr/bin/env bash
# Backup the realm database to ./backups/ and keep the 14 newest files.
#
# Example crontab line (runs daily at 03:00):
#   0 3 * * * cd /path/to/Real\ of\ Villages && ./scripts/backup.sh >> /path/to/Real\ of\ Villages/backups/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p backups

docker compose exec -T db pg_dump -U realm realm | gzip > "backups/realm-$(date +%Y%m%d-%H%M).sql.gz"

# Keep only the 14 newest backup files (portable on macOS and Linux).
ls -1t backups/realm-*.sql.gz | tail -n +15 | while read -r f; do
  rm -f "$f"
done
