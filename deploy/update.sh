#!/usr/bin/env bash
# update.sh — tarik kode terbaru dari GitHub, rebuild image, restart TANPA menghapus data.
#   bash /opt/dahost/deploy/update.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
echo "==> git sync"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"   # riwayat GitHub bisa ditulis ulang (force push) → reset, bukan pull
cd deploy
echo "==> build & restart"
docker compose --env-file .env build --pull
docker compose --env-file .env up -d --remove-orphans
docker image prune -f >/dev/null
echo -n "==> menunggu backend "
for _ in $(seq 1 60); do
  if docker compose --env-file .env exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then echo "OK"; exit 0; fi
  echo -n "."; sleep 4
done
docker compose --env-file .env logs --tail=80 backend
echo "Backend belum sehat — periksa log di atas." >&2; exit 1
