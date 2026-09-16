#!/usr/bin/env bash
# backup.sh — mongodump seluruh database ke deploy/backups/, simpan 14 hari (dipanggil cron harian).
#   bash /opt/dahost/deploy/backup.sh                       → backup sekarang
#   bash /opt/dahost/deploy/backup.sh restore deploy/backups/dahost_erp-2026-09-07_0200.archive.gz
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$APP_DIR/deploy/backups"
KEEP_DAYS=14
cd "$APP_DIR/deploy"
DB_NAME="$(grep '^DB_NAME=' .env | cut -d= -f2)"
if [ "${1:-}" = "restore" ]; then
  FILE="${2:?berkas arsip wajib}"
  echo "==> restore $FILE → db $DB_NAME (data lama DITIMPA)"
  docker compose --env-file .env exec -T mongo mongorestore --archive --gzip --drop --nsInclude="$DB_NAME.*" < "$FILE"
  echo "selesai"; exit 0
fi
mkdir -p "$DEST"
OUT="$DEST/${DB_NAME}-$(date +%F_%H%M).archive.gz"
docker compose --env-file .env exec -T mongo mongodump --db "$DB_NAME" --archive --gzip > "$OUT"
cp -f .env "$DEST/.env.last" && chmod 600 "$DEST/.env.last"
find "$DEST" -name "*.archive.gz" -mtime +$KEEP_DAYS -delete
echo "$(date '+%F %T') backup OK → $OUT ($(du -h "$OUT" | cut -f1))"
