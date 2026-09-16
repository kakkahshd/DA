# Deploy DA ERP (DAHOST) ke VPS — sekali jalan

| Item | Nilai |
|---|---|
| Repo | https://github.com/pandeyoga/DAHOST (branch `main`) |
| VPS | Ubuntu 26.04 LTS · `187.77.116.148` |
| Domain | `dafashionerp.cloud` (+ `www` redirect) |
| SSL | Let's Encrypt via Caddy — **auto-renew**, email `pk.yogaswastika@gmail.com` |
| Stack | Docker Compose: MongoDB 7 · FastAPI · React (nginx) · Caddy |
| Login awal | `admin@garment.com` / `Admin@123` (di-seed otomatis oleh backend — segera ganti) |

## 0. DNS (lakukan lebih dulu, di panel domain)

```
A   dafashionerp.cloud        187.77.116.148
A   www.dafashionerp.cloud    187.77.116.148
```
Jika pakai Cloudflare: mode **DNS only** (awan abu-abu), bukan Proxied.

## 1. Kode untuk terminal VPS

```bash
ssh root@187.77.116.148
```

```bash
apt-get update -y && apt-get install -y git
git clone https://github.com/pandeyoga/DAHOST.git /opt/dahost
bash /opt/dahost/deploy/install_vps.sh
```

Alternatif tanpa clone manual (skrip mandiri, meng-clone sendiri ke `/opt/dahost`):
```bash
curl -fsSL https://raw.githubusercontent.com/pandeyoga/DAHOST/main/deploy/install_vps.sh -o /root/install_vps.sh
bash /root/install_vps.sh
```

Skrip membuat `deploy/.env` (JWT_SECRET acak, **tanpa variabel Emergent**), build image, jalankan,
tunggu `/api/health`, tunggu HTTPS, pasang cron backup 02:00 WIB. Berkas Docker/Caddy sudah ada di
`deploy/`; bila hilang, skrip menulisnya ulang sendiri.

Nilai bawaan sudah `dafashionerp.cloud` / `pk.yogaswastika@gmail.com`. Untuk domain lain:
```bash
DOMAIN=lain.com ACME_EMAIL=x@y.com bash install_vps.sh
```

## 2. Kenapa aman dari "emergent lib"

* `requirements.txt` difilter di dalam image: baris `emergentintegrations` dan `litellm` **dibuang**.
* `backend/routes/marketing_ai_content_tools.py` mengimpor `emergentintegrations` di level modul → tanpa
  penanganan backend **gagal start**. Skrip memasang **stub** kecil (`deploy/emergent_stub/`) yang hanya
  menyediakan kelas `OpenAIImageGeneration`; fitur AI-image akan mengembalikan pesan "tidak tersedia",
  modul lain tidak terpengaruh. `emergentintegrations.llm.chat` sengaja tidak di-stub sehingga `ai_llm.py`
  memakai jalur Anthropic langsungnya (opsional, isi `ANTHROPIC_API_KEY` bila ingin fitur AI).
* `@emergentbase/visual-edits` (devDependency dari aset Emergent) dihapus sebelum `yarn install`.
* `deploy/.env` diverifikasi: skrip berhenti bila ada variabel `EMERGENT*`.
* `backend/.env` & `frontend/.env` tidak dipakai; semua env dari `docker-compose.yml` (`MONGO_URL`,
  `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS`, `REACT_APP_BACKEND_URL`, `WEBAUTHN_*`, `ALLOW_DEMO_SEED=false`).

## 3. Operasional

```bash
bash /opt/dahost/deploy/update.sh                    # tarik kode terbaru + rebuild + restart (data aman)
cd /opt/dahost/deploy && docker compose ps           # status
cd /opt/dahost/deploy && docker compose logs -f backend
cd /opt/dahost/deploy && docker compose logs -f caddy   # status sertifikat SSL
bash /opt/dahost/deploy/backup.sh                    # backup manual → deploy/backups/
bash /opt/dahost/deploy/backup.sh restore deploy/backups/<file>.archive.gz
REGEN=1 bash /opt/dahost/deploy/install_vps.sh       # tulis ulang berkas deploy yang dibuat skrip
```

Volume Docker: `mongo_data` (database), `uploads` (`/app/uploads`), `backups` (`/app/backups`),
`caddy_data` (sertifikat). `docker compose down` **tanpa** `-v` tidak menghapus data.

## 4. Data nyata (go-live) — TIDAK otomatis

Yang di-seed otomatis saat backend start hanya **konfigurasi**: superadmin, roles/permission, COA + posting
profile, proses produksi, kategori produk, satuan. Data demo dimatikan (`ALLOW_DEMO_SEED=false`) dan lokasi
bawaan `GED-*/ZNA-*` dimatikan (`SEED_DEFAULT_LOCATIONS=false`) sesuai keputusan owner.

Data nyata (lokasi, karyawan, warna, kain, aksesoris, model, barang jadi, BOM, vendor, katalog, 25 user, dll.)
dimuat dari **workbook Excel klien** lewat `scripts/import_master_template.py` — mengikuti
`docs/GO_LIVE_RUNBOOK.md`. Berkas itu ada di `private/golive/` yang **di-gitignore**, jadi **tidak ikut ke
GitHub/VPS** — harus diunggah manual:

```bash
# dari laptop (berkas sumber klien):
scp MASTER_DATA_DA_PERBAIKAN_2.xlsx root@187.77.116.148:/opt/dahost/deploy/golive/

# di VPS:
cd /opt/dahost
bash deploy/golive.sh prepare MASTER_DATA_DA_PERBAIKAN_2.xlsx   # susun workbook go-live (+ sheet DAFTAR_PERBAIKAN)
bash deploy/golive.sh gate                                      # gate importir harus hijau
bash deploy/golive.sh check                                     # dry-run → harus 0 kesalahan
bash deploy/golive.sh reset                                     # kosongkan data demo (mongodump dulu, ketik HAPUS), restart backend
bash deploy/golive.sh apply                                     # impor --apply 2× (idempoten)
```
Kalau workbook go-live sudah jadi (`MASTER_DATA_DA_GOLIVE.xlsx`), taruh langsung di `deploy/golive/` dan lewati
`prepare`. Angka yang diharapkan pada impor pertama ada di `docs/GO_LIVE_RUNBOOK.md`
(mis. 10_BOM 464 · 14_KATALOG_JUAL 628 · 17_USER 25). Sandi awal 25 akun: `MASTER_IMPORT_INITIAL_PASSWORD`
di `deploy/.env` (bawaan `Dewi@123`, wajib ganti saat login pertama). Setelah impor: Portal Produksi →
Costing → Terapkan HPP.

Bila VPS sudah terpasang sebelum bagian ini ada: `bash deploy/update.sh` dulu (menambah env
`SEED_DEFAULT_LOCATIONS`, mount `deploy/golive`, dan `mongodump` di image backend), lalu ikuti urutan di atas.

## 5. Catatan

* Folder `deploy/` ikut ter-version di repo DAHOST; `deploy/.env` dan `deploy/backups/` di-gitignore.
* Skrip ini **belum dijalankan/diverifikasi** di VPS (sesuai permintaan). Bila build gagal, kirim 80 baris
  terakhir output — titik rawan yang sudah diberi pengaman: pin pip yang tidak tersedia (fallback per paket),
  RAM kecil saat build React (swap 3GB otomatis bila RAM < 3.5GB), DNS belum propagasi (Caddy retry otomatis).
