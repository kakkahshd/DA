#!/usr/bin/env bash
# vps_resume_restore.sh — lanjutkan vps_timpa_snapshot.sh dari langkah 5 (restore) bila sesi SSH putus.
# Data & sandi sudah disimpan oleh skrip utama di deploy/backups/local_changes_<ts>/.
#   bash deploy/vps_resume_restore.sh dahost_snapshot_2026-09-13.archive.gz
set -euo pipefail
APP_DIR="/opt/dahost"; SRC_DB="test_database"
SNAP="${1:?contoh: bash deploy/vps_resume_restore.sh dahost_snapshot_2026-09-13.archive.gz}"
C='\033[1;36m'; R='\033[0;31m'; N='\033[0m'
log(){ printf "\n${C}==> %s${N}\n" "$*"; }
die(){ printf "${R}GAGAL: %s${N}\n" "$*" >&2; exit 1; }
cd "$APP_DIR/deploy"
DB_NAME="$(grep '^DB_NAME=' .env | cut -d= -f2)"; [ "$DB_NAME" = "dahost_erp" ] || die "DB_NAME bukan dahost_erp."
dc(){ docker compose --env-file .env "$@"; }
[ -f "golive/$SNAP" ] && SNAP="golive/$SNAP"; [ -f "$SNAP" ] || die "snapshot $SNAP tidak ada."
LC_DIR="$(ls -td backups/local_changes_* 2>/dev/null | head -1)"
[ -n "$LC_DIR" ] && [ -s "$LC_DIR/credentials_vps.json" ] || die "credentials_vps.json dari skrip utama tidak ditemukan — jalankan vps_timpa_snapshot.sh dari awal."
echo "memakai sandi tersimpan: $LC_DIR/credentials_vps.json"

log "Kondisi mongo dahost (bila 'Up' baru beberapa detik/menit ⇒ mongod restart saat restore)"
dc ps mongo
docker inspect -f 'restart_count={{.RestartCount}} started={{.State.StartedAt}} oom_killed={{.State.OOMKilled}}' "$(dc ps -q mongo)"
dc logs --tail 15 mongo | grep -iE "error|fatal|killed|shutdown|restart" || echo "(tidak ada error di log mongo)"
for _ in $(seq 1 30); do dc exec -T mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 2; done

log "5. Restore ulang snapshot → $DB_NAME (idempoten, --drop)"
# Dari FILE di dalam container, bukan stdin: exec -T menutup sesi saat stdin habis → indeks tidak selesai dibangun.
docker cp "$SNAP" "$(dc ps -q mongo):/tmp/dahost_snapshot.archive.gz"
MODE="${2:-auto}"   # auto = coba dgn indeks, bila gagal ulang tanpa indeks · noindex = langsung tanpa indeks
ok_restore=0
if [ "$MODE" != "noindex" ]; then
  if dc exec -T mongo mongorestore --archive=/tmp/dahost_snapshot.archive.gz --gzip --drop --numParallelCollections=1 \
       --nsFrom="$SRC_DB.*" --nsTo="$DB_NAME.*" 2>&1 | grep -vE "^\S+\s+(index:|restoring indexes|no indexes|finished restoring|reading metadata|restoring .* from archive)"; then :; fi
  # mongorestore di pipa → cek hasil lewat log 'Failed'
  if dc exec -T mongo mongosh --quiet "$DB_NAME" --eval 'quit(db.rahaza_models.countDocuments()>0?0:1)' 2>/dev/null; then ok_restore=1; fi
fi
log "Diagnosa mongod (untuk akar masalah 'connection closed' saat createIndex)"
docker inspect -f 'restart_count={{.RestartCount}} started={{.State.StartedAt}} oom_killed={{.State.OOMKilled}} status={{.State.Status}}' "$(dc ps -q mongo)"
docker logs --since 10m "$(dc ps -q mongo)" 2>&1 | grep -viE '"c":"NETWORK"|"c":"ACCESS"|"c":"COMMAND"' | grep -iE 'fatal|invariant|assert|abort|shutdown|terminat|signal|error|exception|oom|Killed|index build' | tail -25 || true
dmesg 2>/dev/null | grep -iE 'mongod|oom|killed process' | tail -5 || true
log "5b. Restore ulang TANPA indeks dari dump (backend membuat indeks yang dibutuhkan saat start)"
for _ in $(seq 1 30); do dc exec -T mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 2; done
dc exec -T mongo mongorestore --archive=/tmp/dahost_snapshot.archive.gz --gzip --drop --noIndexRestore --numParallelCollections=1 \
  --nsFrom="$SRC_DB.*" --nsTo="$DB_NAME.*" 2>&1 | grep -vE "^\S+\s+(reading metadata|restoring .* from archive|finished restoring|no indexes)" | tail -15
dc exec -T mongo rm -f /tmp/dahost_snapshot.archive.gz
dc exec -T mongo mongosh --quiet "$DB_NAME" --eval 'quit(db.rahaza_models.countDocuments()>0?0:1)' || die "restore tanpa indeks pun gagal — kirim output ini."
echo "model: $(dc exec -T mongo mongosh --quiet "$DB_NAME" --eval 'print(db.rahaza_models.countDocuments()+" | varian "+db.rahaza_model_variants.countDocuments()+" | BOM "+db.rahaza_boms.countDocuments()+" | COA "+db.rahaza_coa_accounts.countDocuments()+" | toko "+db.marketing_platform_accounts.countDocuments()+" | user "+db.users.countDocuments()+" | koleksi "+db.getCollectionNames().length)' | tr -d '\r')"

log "6. Kembalikan sandi user/kreator VPS"
dc exec -T mongo mongosh --quiet "$DB_NAME" --eval "
  const d=$(cat "$LC_DIR/credentials_vps.json");
  let nu=0,nk=0;
  d.users.forEach(u=>{ if(u.password){ const r=db.users.updateOne({email:u.email},{\$set:{password:u.password,must_change_password:!!u.must_change_password}}); nu+=r.modifiedCount; }});
  d.creators.forEach(c=>{ if(c.login_password_hash){ const r=db.marketing_kol_creators.updateOne({login_email:c.login_email},{\$set:{login_password_hash:c.login_password_hash,must_change_password:!!c.must_change_password}}); nk+=r.modifiedCount; }});
  print('sandi dikembalikan: '+nu+' user, '+nk+' kreator');" | tr -d '\r'

log "7. Restart backend & gate sinkronisasi"
dc restart backend
for _ in $(seq 1 60); do dc exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1 && break; sleep 4; done
dc exec -T backend curl -fsS http://127.0.0.1:8001/api/health >/dev/null || die "backend tidak sehat — lihat: docker compose logs backend"
dc exec -T backend python3 /app/scripts/verify_finance_sync.py || true
dc exec -T backend python3 /app/scripts/verify_master_sync.py || true
dc exec -T backend python3 /app/scripts/verify_data_integrity.py || true

log "SELESAI"
echo "Situs: https://$(grep '^DOMAIN=' .env | cut -d= -f2) · admin@garment.com / Admin@123 · staf: Dewi@123 (wajib ganti) · kreator KOL: Dewi@123"
