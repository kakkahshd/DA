#!/usr/bin/env bash
# install_vps.sh — pasang DA ERP (repo pandeyoga/DAHOST) di VPS Ubuntu 22.04/24.04/26.04 SEKALI JALAN.
#
# Arsitektur (Docker Compose): MongoDB 7 + FastAPI (uvicorn) + React build (nginx) + Caddy
# (HTTPS Let's Encrypt otomatis + AUTO-RENEW, tanpa cron tambahan).
#
# Cara pakai (sebagai root di VPS):
#   bash install_vps.sh
# Nilai bawaan sudah diisi untuk dafashionerp.cloud; bisa ditimpa lewat env:
#   DOMAIN=lain.com ACME_EMAIL=x@y.com bash install_vps.sh
#
# Idempoten: aman dijalankan ulang (git sync + rebuild + restart; deploy/.env & data Mongo tidak ditimpa).
# Skrip ini MANDIRI: semua berkas Docker/Caddy dibuat oleh skrip ini, sehingga repo tidak wajib punya folder deploy/.
set -euo pipefail

DOMAIN="${DOMAIN:-dafashionerp.cloud}"
ACME_EMAIL="${ACME_EMAIL:-pk.yogaswastika@gmail.com}"
EXPECTED_IP="${EXPECTED_IP:-187.77.116.148}"
REPO_URL="${REPO_URL:-https://github.com/pandeyoga/DAHOST.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/dahost}"
REGEN="${REGEN:-0}"          # REGEN=1 → tulis ulang berkas deploy yang sudah ada
ENV_FILE="$APP_DIR/deploy/.env"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "Jalankan sebagai root (ssh root@$EXPECTED_IP)."
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "DOMAIN tidak valid: $DOMAIN"

# ───────────────────────────── 1. Paket dasar ─────────────────────────────
log "1/9 Paket dasar (Ubuntu $(. /etc/os-release && echo "$VERSION_ID"))"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw dnsutils openssl >/dev/null
timedatectl set-timezone Asia/Jakarta 2>/dev/null || true

# ───────────────────────────── 2. Swap (build React butuh RAM) ────────────
log "2/9 Memori & swap"
RAM_MB="$(free -m | awk '/^Mem:/{print $2}')"
SWAP_MB="$(free -m | awk '/^Swap:/{print $2}')"
echo "RAM ${RAM_MB}MB · swap ${SWAP_MB}MB"
if [ "$RAM_MB" -lt 3500 ] && [ "$SWAP_MB" -lt 1024 ] && [ ! -f /swapfile ]; then
  echo "RAM < 3.5GB → membuat swap 3GB agar build frontend tidak OOM"
  fallocate -l 3G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ───────────────────────────── 3. Docker ──────────────────────────────────
log "3/9 Docker + Compose"
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y -qq docker.io docker-compose-v2 >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null
if [ ! -f /etc/docker/daemon.json ]; then
  mkdir -p /etc/docker
  echo '{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }' > /etc/docker/daemon.json
  systemctl restart docker
fi
docker compose version >/dev/null 2>&1 || apt-get install -y -qq docker-compose-v2 >/dev/null
echo "docker $(docker --version | cut -d' ' -f3) · compose $(docker compose version --short)"

# ───────────────────────────── 4. Firewall ────────────────────────────────
log "4/9 Firewall (SSH, 80, 443)"
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n 1,6p

# ───────────────────────────── 5. DNS ─────────────────────────────────────
log "5/9 Cek DNS $DOMAIN"
SERVER_IP="$(curl -fsS4 --max-time 8 https://api.ipify.org || hostname -I | awk '{print $1}')"
DNS_IP="$(dig +short A "$DOMAIN" @1.1.1.1 | tail -n1 || true)"
[ "$SERVER_IP" = "$EXPECTED_IP" ] || warn "IP server terdeteksi $SERVER_IP (diharapkan $EXPECTED_IP)."
if [ "$DNS_IP" = "$SERVER_IP" ]; then
  echo "OK: $DOMAIN → $SERVER_IP"
else
  warn "DNS $DOMAIN → '${DNS_IP:-kosong}', IP server $SERVER_IP."
  warn "Buat A record: $DOMAIN → $SERVER_IP (dan www → $SERVER_IP), TANPA proxy Cloudflare (DNS only)."
  warn "Instalasi dilanjutkan; Caddy akan mencoba ulang sertifikat otomatis setelah DNS benar."
fi

# ───────────────────────────── 6. Kode sumber ─────────────────────────────
log "6/9 Kode sumber → $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
fi
mkdir -p "$APP_DIR/deploy/emergent_stub/emergentintegrations/llm/openai" "$APP_DIR/deploy/golive"
cd "$APP_DIR"

# tulis berkas hanya bila belum ada (atau REGEN=1) → versi di repo (bila ada) tidak ditimpa
put() { # put <path> ; isi dari stdin
  if [ -f "$1" ] && [ "$REGEN" != 1 ]; then cat >/dev/null; echo "  ada : $1"; else cat > "$1"; echo "  tulis: $1"; fi
}

put .dockerignore <<'EOF'
.git
**/node_modules
frontend/build
**/__pycache__
**/*.pyc
backend/.env
frontend/.env
deploy/.env
deploy/backups
/backups
/test_reports
/memory
/docs
/tests
/mobile
/data_import
/samples
/.emergent
/.logs
/*.md
/*.json
/*.csv
/backend_test*.py
/test_*.py
/verify_*.py
backend/tests
backend/backend_test*.py
backend/test_*.py
EOF

# Stub `emergentintegrations`: satu berkas di repo (routes/marketing_ai_content_tools.py) mengimpor
# pustaka Emergent di level modul. Tanpa stub ini backend GAGAL START di VPS. Stub hanya
# menyediakan kelas yang diimpor; saat dipakai ia mengembalikan error yang jelas (fitur AI-image
# butuh kunci Emergent, tidak tersedia di VPS). `emergentintegrations.llm.chat` sengaja TIDAK
# disediakan agar `ai_llm.py` jatuh ke implementasi Anthropic langsung miliknya sendiri.
put deploy/emergent_stub/emergentintegrations/__init__.py <<'EOF'
"""Stub minimal pengganti emergentintegrations (hanya untuk deploy VPS)."""
EOF
put deploy/emergent_stub/emergentintegrations/llm/__init__.py <<'EOF'
EOF
put deploy/emergent_stub/emergentintegrations/llm/openai/__init__.py <<'EOF'
EOF
put deploy/emergent_stub/emergentintegrations/llm/openai/image_generation.py <<'EOF'
class OpenAIImageGeneration:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("AI image generation tidak tersedia di server ini (butuh Emergent Universal Key).")
EOF

put deploy/Dockerfile.backend <<'EOF'
# DA ERP backend — Python 3.11 (sama dengan lingkungan pengembangan).
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Jakarta

RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential libffi-dev tzdata \
    && (ARCH="$(dpkg --print-architecture)"; if [ "$ARCH" = "amd64" ]; then \
         curl -fsSL -o /tmp/mt.deb https://fastdl.mongodb.org/tools/db/mongodb-database-tools-debian12-x86_64-100.12.0.deb \
         && apt-get install -y /tmp/mt.deb && rm -f /tmp/mt.deb || echo "mongodb-database-tools dilewati (backup dari UI nonaktif; backup harian tetap jalan via cron host)"; fi) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt .
# emergentintegrations & litellm hanya ada di lingkungan Emergent → DIBUANG. Sisanya dipasang;
# bila pemasangan massal gagal karena satu pin, jatuh ke pemasangan per paket (yang gagal dilewati).
RUN grep -viE '^(emergentintegrations|litellm)' requirements.txt > /tmp/req.txt \
    && (pip install --no-cache-dir -r /tmp/req.txt \
        || (echo "!! pemasangan massal gagal → per paket"; \
            while read -r p; do [ -z "$p" ] && continue; pip install --no-cache-dir "$p" || echo "SKIP: $p"; done < /tmp/req.txt))
RUN python -c "import fastapi, motor, uvicorn, bcrypt, jwt, pandas, openpyxl, reportlab, fpdf" \
    && echo "dependensi inti OK"

COPY deploy/emergent_stub/ /usr/local/lib/python3.11/site-packages/
COPY backend/ .
COPY scripts/ /app/scripts/
RUN rm -f .env && chmod +x /app/scripts/*.sh 2>/dev/null || true; mkdir -p /app/uploads /app/backups

EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips=*"]
EOF

put deploy/Dockerfile.frontend <<'EOF'
# DA ERP frontend — build CRA/craco lalu sajikan statis lewat nginx (SPA fallback ke index.html).
FROM node:20-alpine AS build
WORKDIR /app/frontend
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL \
    GENERATE_SOURCEMAP=false \
    DISABLE_ESLINT_PLUGIN=true \
    CI=false
COPY frontend/package.json ./
# @emergentbase/visual-edits = alat editor Emergent (hanya dev server) → dibuang agar tidak menarik aset eksternal.
RUN node -e "const f='package.json',p=require('./'+f);delete (p.devDependencies||{})['@emergentbase/visual-edits'];require('fs').writeFileSync(f,JSON.stringify(p,null,2))" \
    && yarn install --network-timeout 600000
COPY frontend/ .
RUN rm -f .env \
    && node -e "const f='package.json',p=require('./'+f);delete (p.devDependencies||{})['@emergentbase/visual-edits'];require('fs').writeFileSync(f,JSON.stringify(p,null,2))" \
    && NODE_OPTIONS=--max-old-space-size=2560 npx craco build \
    && test -f build/index.html

FROM nginx:1.27-alpine
COPY deploy/nginx-frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/build /usr/share/nginx/html
EXPOSE 80
EOF

put deploy/nginx-frontend.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;

    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files $uri /index.html;
        add_header Cache-Control "no-cache";
    }
}
EOF

put deploy/Caddyfile <<'EOF'
{
    email {$ACME_EMAIL}
}

# Caddy mengurus sertifikat Let's Encrypt otomatis + PERPANJANGAN otomatis (tanpa cron tambahan).
{$DOMAIN} {
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }

    # Semua /api/* → FastAPI
    handle /api/* {
        reverse_proxy backend:8001 {
            header_up X-Forwarded-Proto {scheme}
            transport http {
                read_timeout 300s
            }
        }
    }

    # Sisanya → SPA React
    handle {
        reverse_proxy frontend:80
    }

    request_body {
        max_size 100MB
    }

    log {
        output file /data/access.log {
            roll_size 50mb
            roll_keep 5
        }
    }
}

www.{$DOMAIN} {
    redir https://{$DOMAIN}{uri} permanent
}
EOF

put deploy/docker-compose.yml <<'EOF'
name: dahost

services:
  mongo:
    image: mongo:7
    restart: unless-stopped
    command: ["mongod", "--bind_ip_all", "--quiet", "--wiredTigerCacheSizeGB", "1"]
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 15s
      timeout: 5s
      retries: 10

  backend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    restart: unless-stopped
    depends_on:
      mongo:
        condition: service_healthy
    environment:
      ENV: production
      TZ: Asia/Jakarta
      MONGO_URL: mongodb://mongo:27017
      DB_NAME: ${DB_NAME}
      JWT_SECRET: ${JWT_SECRET}
      CORS_ORIGINS: https://${DOMAIN}
      REACT_APP_BACKEND_URL: https://${DOMAIN}
      API_URL: https://${DOMAIN}
      BASE_URL: https://${DOMAIN}
      WEBAUTHN_RP_ID: ${DOMAIN}
      WEBAUTHN_ORIGIN: https://${DOMAIN}
      WEBAUTHN_RP_NAME: DA ERP
      ALLOW_DEMO_SEED: "false"
      SEED_DEFAULT_LOCATIONS: "false"
      MASTER_IMPORT_INITIAL_PASSWORD: ${MASTER_IMPORT_INITIAL_PASSWORD}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    volumes:
      - uploads:/app/uploads
      - backups:/app/backups
      - ./golive:/app/private/golive
    expose:
      - "8001"

  frontend:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.frontend
      args:
        REACT_APP_BACKEND_URL: https://${DOMAIN}
    restart: unless-stopped
    expose:
      - "80"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on:
      - backend
      - frontend
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      DOMAIN: ${DOMAIN}
      ACME_EMAIL: ${ACME_EMAIL}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  mongo_data:
  uploads:
  backups:
  caddy_data:
  caddy_config:
EOF

put deploy/update.sh <<'EOF'
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
EOF

put deploy/backup.sh <<'EOF'
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
EOF
chmod +x deploy/update.sh deploy/backup.sh deploy/golive.sh 2>/dev/null || true

# ───────────────────────────── 7. .env ────────────────────────────────────
log "7/9 Berkas rahasia $ENV_FILE (tidak ditimpa bila sudah ada) — TANPA variabel Emergent"
if [ -f "$ENV_FILE" ]; then
  echo "Memakai $ENV_FILE yang sudah ada."
  sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|;s|^ACME_EMAIL=.*|ACME_EMAIL=$ACME_EMAIL|" "$ENV_FILE"
  grep -q '^ANTHROPIC_API_KEY=' "$ENV_FILE" || echo "ANTHROPIC_API_KEY=" >> "$ENV_FILE"
  grep -q '^MASTER_IMPORT_INITIAL_PASSWORD=' "$ENV_FILE" || echo "MASTER_IMPORT_INITIAL_PASSWORD=Dewi@123" >> "$ENV_FILE"
else
  {
    echo "DOMAIN=$DOMAIN"
    echo "ACME_EMAIL=$ACME_EMAIL"
    echo "DB_NAME=dahost_erp"
    echo "JWT_SECRET=$(openssl rand -hex 48)"
    echo "MASTER_IMPORT_INITIAL_PASSWORD=Dewi@123"
    echo "ANTHROPIC_API_KEY="
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Dibuat: $ENV_FILE"
fi
if grep -qiE 'EMERGENT|litellm' "$ENV_FILE"; then die "$ENV_FILE mengandung variabel Emergent — hapus dulu."; fi

# ───────────────────────────── 8. Build & run ─────────────────────────────
log "8/9 Build & jalankan (build pertama ±8–15 menit, tergantung VPS)"
cd "$APP_DIR/deploy"
dc() { docker compose --env-file "$ENV_FILE" "$@"; }
dc build --pull
dc up -d --remove-orphans

echo -n "Menunggu backend sehat (seed awal bisa 1–3 menit) "
BE_OK=0
for _ in $(seq 1 90); do
  if dc exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then BE_OK=1; echo " OK"; break; fi
  echo -n "."; sleep 4
done
[ "$BE_OK" = 1 ] || { dc logs --tail=80 backend; die "Backend belum sehat — lihat log di atas."; }

echo -n "Menunggu HTTPS https://$DOMAIN "
HTTPS_OK=0
for _ in $(seq 1 36); do
  if curl -fsS --max-time 8 "https://$DOMAIN/api/health" >/dev/null 2>&1; then HTTPS_OK=1; echo " OK"; break; fi
  echo -n "."; sleep 5
done
[ "$HTTPS_OK" = 1 ] || warn "HTTPS belum aktif — biasanya DNS belum mengarah ke $SERVER_IP. Caddy mencoba ulang otomatis. Log: cd $APP_DIR/deploy && docker compose logs -f caddy"

# ───────────────────────────── 9. Cron backup ─────────────────────────────
log "9/9 Backup MongoDB harian (02:00 WIB, simpan 14 hari)"
cat > /etc/cron.d/dahost-backup <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 2 * * * root $APP_DIR/deploy/backup.sh >> /var/log/dahost-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/dahost-backup

cat <<SUMMARY

==================================================================
 DA ERP terpasang.
   URL            : https://$DOMAIN
   Login awal     : admin@garment.com / Admin@123   ← SEGERA ganti password lewat menu Admin
   Folder app     : $APP_DIR
   Rahasia        : $ENV_FILE  (JWT_SECRET — backup berkas ini!)
   SSL            : Let's Encrypt via Caddy, auto-renew, notifikasi ke $ACME_EMAIL

 Perintah harian:
   Update kode    : bash $APP_DIR/deploy/update.sh
   Status         : cd $APP_DIR/deploy && docker compose ps
   Log backend    : cd $APP_DIR/deploy && docker compose logs -f backend
   Log SSL/Caddy  : cd $APP_DIR/deploy && docker compose logs -f caddy
   Backup manual  : bash $APP_DIR/deploy/backup.sh
   Restore        : bash $APP_DIR/deploy/backup.sh restore <berkas.archive.gz>
   Restart semua  : cd $APP_DIR/deploy && docker compose restart

 DATA NYATA (go-live) — belum dimuat, dilakukan terpisah (lihat deploy/README_DEPLOY.md §5):
   scp MASTER_DATA_DA_PERBAIKAN_2.xlsx root@$SERVER_IP:$APP_DIR/deploy/golive/
   bash $APP_DIR/deploy/golive.sh prepare MASTER_DATA_DA_PERBAIKAN_2.xlsx
   bash $APP_DIR/deploy/golive.sh check && bash $APP_DIR/deploy/golive.sh reset && bash $APP_DIR/deploy/golive.sh apply

 Fitur AI (opsional): isi ANTHROPIC_API_KEY di $ENV_FILE lalu
   cd $APP_DIR/deploy && docker compose up -d backend
==================================================================
SUMMARY
