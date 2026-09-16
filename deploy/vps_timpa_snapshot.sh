#!/usr/bin/env bash
# vps_timpa_snapshot.sh — KHUSUS VPS srv1957551 (/opt/dahost, compose "dahost", DB dahost_erp).
# Menimpa DB DAHOST dengan snapshot preview yang sudah sinkron, TANPA menyentuh proyek lain (kn-*).
#
#   1) Save to GitHub di Emergent  2) scp snapshot ke VPS  3) jalankan:
#      bash /opt/dahost/deploy/vps_timpa_snapshot.sh dahost_snapshot_2026-09-13.archive.gz
#
# Urutan: pagar pengaman → simpan perubahan lokal git → backup DB → simpan sandi yang sudah diganti user
#         → update kode (git + rebuild) → mongorestore (test_database → dahost_erp) → kembalikan sandi
#         → restart backend → gate sinkronisasi.
set -euo pipefail
APP_DIR="/opt/dahost"
EXPECT_REMOTE="pandeyoga/DAHOST"
EXPECT_PROJECT="dahost"
EXPECT_DB="dahost_erp"
SRC_DB="test_database"
SNAP="${1:?contoh: bash deploy/vps_timpa_snapshot.sh dahost_snapshot_2026-09-13.archive.gz}"

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[1;36m'; N='\033[0m'
log(){ printf "\n${C}==> %s${N}\n" "$*"; }
die(){ printf "${R}GAGAL: %s${N}\n" "$*" >&2; exit 1; }
TS="$(date +%Y-%m-%d_%H%M)"

# ── 0. Pagar pengaman: pastikan ini benar-benar DAHOST, bukan proyek lain ─────────────
log "0. Pagar pengaman"
[ -d "$APP_DIR/.git" ] || die "$APP_DIR bukan repo git."
git -C "$APP_DIR" remote get-url origin | grep -q "$EXPECT_REMOTE" || die "remote origin bukan $EXPECT_REMOTE."
cd "$APP_DIR/deploy"
[ -f .env ] || die "deploy/.env tidak ada."
DB_NAME="$(grep '^DB_NAME=' .env | cut -d= -f2)"
[ "$DB_NAME" = "$EXPECT_DB" ] || die "DB_NAME di .env = '$DB_NAME', diharapkan $EXPECT_DB."
PROJECT="$(grep '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2 || true)"; PROJECT="${PROJECT:-$(basename "$APP_DIR")}"
[ "$PROJECT" = "$EXPECT_PROJECT" ] || die "Nama proyek compose '$PROJECT' ≠ $EXPECT_PROJECT."
dc(){ docker compose --env-file .env "$@"; }
MONGO_CTN="$(dc ps -q mongo)"; [ -n "$MONGO_CTN" ] || die "container mongo proyek dahost tidak jalan."
docker inspect -f '{{.Name}}' "$MONGO_CTN" | grep -q "^/${EXPECT_PROJECT}-mongo" || die "container mongo bukan milik dahost."
[ -f "golive/$SNAP" ] || [ -f "$SNAP" ] || die "snapshot $SNAP tidak ada — scp dulu ke $APP_DIR/deploy/golive/."
[ -f "golive/$SNAP" ] && SNAP="golive/$SNAP"
gzip -t "$SNAP" 2>/dev/null || die "snapshot rusak (bukan gzip valid)."
printf "${G}OK${N} repo=%s  proyek=%s  DB=%s  mongo=%s  snapshot=%s (%s)\n" "$EXPECT_REMOTE" "$PROJECT" "$DB_NAME" \
  "$(docker inspect -f '{{.Name}}' "$MONGO_CTN" | tr -d /)" "$SNAP" "$(du -h "$SNAP" | cut -f1)"
echo "Proyek lain yang TIDAK disentuh: $(docker ps --format '{{.Names}}' | grep -v "^${EXPECT_PROJECT}-" | tr '\n' ' ')"

JE="$(dc exec -T mongo mongosh --quiet "$DB_NAME" --eval 'print(db.rahaza_journal_entries.countDocuments()+db.marketing_orders.countDocuments()+db.dewi_attendance.countDocuments()+db.production_work_orders.countDocuments())' | tr -d '\r')"
if [ "${JE:-0}" != "0" ]; then
  printf "${Y}PERINGATAN: DB VPS sudah berisi %s transaksi nyata (jurnal/order/absensi/WO). Menimpa akan MENGHAPUSNYA.${N}\n" "$JE"
fi
printf "\n${Y}DB %s akan DITIMPA dengan snapshot. Backup dibuat dulu. Ketik TIMPA untuk lanjut: ${N}" "$DB_NAME"
read -r ans; [ "$ans" = "TIMPA" ] || { echo "Dibatalkan."; exit 1; }

# ── 1. Simpan perubahan lokal git (mis. Caddyfile yang diedit tangan) ─────────────────
log "1. Perubahan lokal di repo (akan dipertahankan)"
LC_DIR="backups/local_changes_$TS"; mkdir -p "$LC_DIR"
CHANGED="$(git -C "$APP_DIR" status --porcelain | awk '{print $2}')"
if [ -n "$CHANGED" ]; then
  echo "$CHANGED" | tee "$LC_DIR/files.txt"
  git -C "$APP_DIR" diff > "$LC_DIR/local.patch" || true
  for f in $CHANGED; do [ -f "$APP_DIR/$f" ] && { mkdir -p "$LC_DIR/$(dirname "$f")"; cp -a "$APP_DIR/$f" "$LC_DIR/$f"; }; done
  echo "disalin ke deploy/$LC_DIR"
else
  echo "tidak ada perubahan lokal."
fi

# ── 2. Backup DB VPS ──────────────────────────────────────────────────────────────────
log "2. Backup DB $DB_NAME"
bash "$APP_DIR/deploy/backup.sh"
LAST_BK="$(ls -t backups/${DB_NAME}-*.archive.gz | head -1)"; [ -s "$LAST_BK" ] || die "backup tidak terbentuk."
echo "backup: $LAST_BK ($(du -h "$LAST_BK" | cut -f1))"

# ── 3. Simpan sandi yang mungkin sudah diganti user di VPS ────────────────────────────
log "3. Simpan sandi user & kreator KOL dari VPS (agar tidak ter-reset)"
dc exec -T mongo mongosh --quiet "$DB_NAME" --eval '
  const u=db.users.find({},{email:1,password:1,must_change_password:1,_id:0}).toArray();
  const k=db.marketing_kol_creators.find({login_password_hash:{$exists:true}},{login_email:1,login_password_hash:1,must_change_password:1,_id:0}).toArray();
  print(JSON.stringify({users:u,creators:k}));' | tr -d '\r' > "$LC_DIR/credentials_vps.json"
echo "tersimpan: $(python3 -c "import json;d=json.load(open('$LC_DIR/credentials_vps.json'));print(len(d['users']),'user,',len(d['creators']),'kreator')" 2>/dev/null || echo '?')"
chmod 600 "$LC_DIR/credentials_vps.json"

# ── 4. Update kode: git + rebuild + restart (hanya proyek dahost) ─────────────────────
log "4. Update kode dari GitHub & rebuild"
bash "$APP_DIR/deploy/update.sh"
if [ -n "$CHANGED" ]; then
  log "4b. Kembalikan perubahan lokal"
  if ! git -C "$APP_DIR" apply --3way "$LC_DIR/local.patch" 2>/dev/null; then
    for f in $CHANGED; do [ -f "$LC_DIR/$f" ] && cp -a "$LC_DIR/$f" "$APP_DIR/$f" && echo "disalin balik: $f"; done
  fi
  git -C "$APP_DIR" status --short
  case "$CHANGED" in *Caddyfile*) dc restart caddy; echo "caddy di-restart (Caddyfile lokal dipertahankan)";; esac
fi

# ── 5. Restore snapshot (test_database → dahost_erp) ──────────────────────────────────
log "5. Restore snapshot → $DB_NAME"
# Dari FILE di dalam container, bukan stdin: exec -T menutup sesi saat stdin habis → indeks tidak selesai dibangun.
docker cp "$SNAP" "$(dc ps -q mongo):/tmp/dahost_snapshot.archive.gz"
dc exec -T mongo mongorestore --archive=/tmp/dahost_snapshot.archive.gz --gzip --drop --numParallelCollections=1 \
  --nsFrom="$SRC_DB.*" --nsTo="$DB_NAME.*"
dc exec -T mongo rm -f /tmp/dahost_snapshot.archive.gz
echo "model: $(dc exec -T mongo mongosh --quiet "$DB_NAME" --eval 'print(db.rahaza_models.countDocuments()+" | varian "+db.rahaza_model_variants.countDocuments()+" | BOM "+db.rahaza_boms.countDocuments()+" | COA "+db.rahaza_coa_accounts.countDocuments()+" | toko "+db.marketing_platform_accounts.countDocuments()+" | user "+db.users.countDocuments())' | tr -d '\r')"

# ── 6. Kembalikan sandi VPS (yang emailnya sama) ──────────────────────────────────────
log "6. Kembalikan sandi user/kreator VPS"
dc exec -T mongo mongosh --quiet "$DB_NAME" --eval "
  const d=$(cat "$LC_DIR/credentials_vps.json");
  let nu=0,nk=0;
  d.users.forEach(u=>{ if(u.password){ const r=db.users.updateOne({email:u.email},{\$set:{password:u.password,must_change_password:!!u.must_change_password}}); nu+=r.modifiedCount; }});
  d.creators.forEach(c=>{ if(c.login_password_hash){ const r=db.marketing_kol_creators.updateOne({login_email:c.login_email},{\$set:{login_password_hash:c.login_password_hash,must_change_password:!!c.must_change_password}}); nk+=r.modifiedCount; }});
  print('sandi dikembalikan: '+nu+' user, '+nk+' kreator');" | tr -d '\r'

# ── 7. Restart backend → sinkronisasi startup → gate ─────────────────────────────────
log "7. Restart backend & gate sinkronisasi"
dc restart backend
for _ in $(seq 1 60); do dc exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1 && break; sleep 4; done
dc exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null || die "backend tidak sehat — lihat: docker compose logs backend"
dc exec -T backend python3 /app/scripts/verify_finance_sync.py || true
dc exec -T backend python3 /app/scripts/verify_master_sync.py || true
dc exec -T backend python3 /app/scripts/verify_data_integrity.py || true

log "SELESAI"
cat <<EOF
Situs      : https://$(grep '^DOMAIN=' .env | cut -d= -f2)
Superadmin : admin@garment.com / Admin@123  (segera ganti)
25 staf    : email masing-masing / Dewi@123  → wajib ganti saat login pertama
             (yang sudah pernah mengganti sandi di VPS TETAP memakai sandi barunya)
Kreator KOL: login_email @creator.id / Dewi@123 → wajib ganti
Backup DB lama : $APP_DIR/deploy/$LAST_BK  (kembalikan: bash deploy/backup.sh restore $LAST_BK)
Perubahan lokal: $APP_DIR/deploy/$LC_DIR
Proyek kn-* tidak disentuh.
EOF
