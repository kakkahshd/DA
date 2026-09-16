#!/usr/bin/env bash
# inspect_vps.sh — HANYA MEMBACA. Menampilkan kondisi VPS supaya skrip deploy tidak salah proyek.
# Rahasia (password/URI) dimasker. Jalankan: bash inspect_vps.sh  (atau tempel isinya ke terminal VPS)
set +e
APP_DIR="${1:-/opt/dahost}"
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
mask(){ sed -E 's/((PASS|PASSWORD|SECRET|KEY|TOKEN|URI|URL)[A-Z_]*=)(.*)/\1***/I'; }

hr "1. Host"; hostname; uname -a; date; df -h / | tail -1; free -h | head -2

hr "2. Semua container Docker (proyek lain ikut terlihat)"
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
hr "2b. Proyek docker compose yang terdaftar"; docker compose ls -a 2>/dev/null

hr "3. Folder aplikasi kandidat"
for d in /opt/* /srv/* /var/www/* /home/*/*; do [ -d "$d/.git" ] && printf '%s  →  %s\n' "$d" "$(git -C "$d" remote get-url origin 2>/dev/null)"; done

hr "4. DAHOST di $APP_DIR"
if [ -d "$APP_DIR" ]; then
  git -C "$APP_DIR" remote -v | head -2
  echo "branch: $(git -C "$APP_DIR" branch --show-current)  commit: $(git -C "$APP_DIR" log -1 --format='%h %ad %s' --date=short)"
  echo "perubahan lokal: $(git -C "$APP_DIR" status --porcelain | wc -l) berkas"
  ls -la "$APP_DIR/deploy" | grep -E '\.env|golive|backups|docker-compose' 
  echo "-- deploy/.env (nilai dimasker) --"; [ -f "$APP_DIR/deploy/.env" ] && mask < "$APP_DIR/deploy/.env"
  echo "-- isi deploy/golive & backups --"; ls -la "$APP_DIR/deploy/golive" "$APP_DIR/deploy/backups" 2>/dev/null
else
  echo "TIDAK ADA $APP_DIR — sebutkan folder yang benar: bash inspect_vps.sh /path/aplikasi"
fi

hr "5. Database di container mongo DAHOST"
if [ -f "$APP_DIR/deploy/docker-compose.yml" ]; then
  cd "$APP_DIR/deploy" || exit 0
  DBN="$(grep '^DB_NAME=' .env 2>/dev/null | cut -d= -f2)"; echo "DB_NAME di .env: ${DBN:-<kosong>}"
  docker compose --env-file .env exec -T mongo mongosh --quiet --eval '
    db.adminCommand({listDatabases:1}).databases.forEach(d=>print("db:",d.name,(d.sizeOnDisk/1e6).toFixed(1),"MB"))' 2>/dev/null
  echo "-- jumlah dokumen di $DBN (untuk memutuskan Jalur A/B) --"
  docker compose --env-file .env exec -T mongo mongosh --quiet "$DBN" --eval '
    const c=["users","rahaza_coa_accounts","rahaza_models","rahaza_model_variants","rahaza_boms","rahaza_materials",
             "rahaza_journal_entries","marketing_platform_accounts","marketing_orders","marketing_settlements",
             "marketing_platform_withdrawals","dewi_attendance","production_work_orders","rahaza_sales_orders","rahaza_purchase_orders"];
    c.forEach(n=>print(n.padEnd(34), db.getCollection(n).countDocuments()));
    const je=db.rahaza_journal_entries.find({},{date:1,source_module:1,status:1}).sort({created_at:-1}).limit(3).toArray();
    print("3 jurnal terakhir:", JSON.stringify(je));
    const u=db.users.find({},{email:1,role:1,last_login:1}).limit(30).toArray(); print("users:", JSON.stringify(u));' 2>/dev/null
fi

hr "6. Port & web server"
ss -ltnp 2>/dev/null | grep -E ':(80|443|3000|8001|27017|8080|5000)\b' 
ls /etc/nginx/sites-enabled 2>/dev/null; grep -rh "server_name" /etc/nginx/sites-enabled 2>/dev/null | sort -u
ls /etc/caddy/Caddyfile 2>/dev/null && grep -E '^[a-z0-9.-]+ *\{' /etc/caddy/Caddyfile

hr "7. Cron / systemd milik proyek"
crontab -l 2>/dev/null | grep -v '^#'; systemctl list-units --type=service --state=running 2>/dev/null | grep -iE 'dahost|docker|nginx|caddy|mongo|node|uvicorn|pm2'
echo; echo "Selesai — tempel seluruh output ini ke chat."
