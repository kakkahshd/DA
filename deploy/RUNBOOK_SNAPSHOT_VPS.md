# Runbook — Bawa data siap pakai dari preview ke VPS (dafashionerp.cloud)

Snapshot DB preview (master klien + COA 4-digit + semua sinkronisasi hijau, TANPA data uji):
`dahost_snapshot_2026-09-13.archive.gz` (≈550 KB). Unduh dari preview:
`https://dahost-staging.preview.emergentagent.com/api/uploads/dahost_snapshot_2026-09-13.archive.gz`

Gate yang hijau saat snapshot dibuat: `verify_finance_sync.py` 9/9 · `verify_master_sync.py` 10/10 ·
`verify_data_integrity.py` 24/24 · `verify_pencairan_finance.py` 27/27.

## 1. Simpan kode terbaru ke GitHub
Klik **Save to GitHub** di chat Emergent (repo `pandeyoga/DAHOST`).

## 2. Di laptop — kirim snapshot ke VPS
```bash
scp dahost_snapshot_2026-09-13.archive.gz root@187.77.116.148:/opt/dahost/deploy/golive/
```

## 3. Di VPS — pilih SATU jalur sesuai kondisi data DA di VPS

**Cek dulu**: apakah di VPS sudah ada transaksi nyata yang diketik user (order, jurnal, absensi, WO) sejak `golive.sh apply`?

### Jalur A — VPS hanya berisi hasil skrip impor (belum ada transaksi nyata) → TIMPA dengan snapshot
```bash
ssh root@187.77.116.148
cd /opt/dahost
bash deploy/update.sh                                   # git pull + rebuild + restart (data lama aman)
bash deploy/golive.sh restore-snapshot dahost_snapshot_2026-09-13.archive.gz
#   → backup DB lama dulu → ketik TIMPA → mongorestore (test_database → dahost_erp) → restart backend → gate sinkronisasi
```
Snapshot = hasil impor Excel yang SAMA dengan yang dipakai skrip + semua perbaikan setelahnya (COA 4-digit, subledger per toko/vendor/bank,
flags akun pendapatan, rekening pencairan default, konversi satuan, dsb). Jadi data skrip **tidak hilang** — snapshot adalah versinya yang sudah disinkronkan.

### Jalur B — VPS sudah berisi transaksi nyata → JANGAN timpa, cukup update + sinkron
```bash
ssh root@187.77.116.148
cd /opt/dahost
bash deploy/update.sh
bash deploy/golive.sh sync-check
```
Saat backend start, sinkronisasi idempoten berjalan otomatis pada data yang sudah ada: seed & migrasi COA 4-digit, subledger otomatis
(1-1303-xxx per toko, vendor, bank, pelanggan), tautan toko ↔ akun pendapatan/piutang/rekening pencairan (default 1-1201),
pemulihan flags akun pendapatan, sinkron master produk (style ↔ varian ↔ BOM ↔ FG), kelompok arus kas.
`sync-check` menjalankan gate `verify_finance_sync`, `verify_master_sync`, `verify_data_integrity` — semua harus HIJAU.
Yang **tidak** ikut otomatis di Jalur B (tidak ada di VPS karena dibuat setelah impor): tidak ada — semua perbaikan berbentuk kode/sinkronisasi, bukan data manual.

Login: `admin@garment.com` / `Admin@123` (25 akun staf: sandi awal `Dewi@123`, wajib ganti saat login pertama).

## 4. Yang harus DIISI pemilik/user setelah live (semua lewat UI/Excel, tanpa skrip)
| Kekurangan | Jumlah | Cara termudah |
|---|---|---|
| Aksesoris/bahan BOM per model | 104 model belum ada aksesoris, 54 belum punya BOM sama sekali | Portal Keuangan → Master Akuntansi → **Impor Harga · Rekening · BOM** → unduh template → sheet **BOM_AKSESORIS** (satu baris per bahan per model, contoh baris sudah ada) → unggah. Atau per model: RnD → Master Produk → tombol *Salin BOM ke varian* / *Tambah aksesoris massal*. |
| Berat model (ongkir) | 104 | Template yang sama, sheet **MODEL** kolom `berat_gram`. |
| Harga & satuan beli material | material tanpa harga | Template yang sama, sheet **MATERIAL** (`satuan_beli`, `isi_per_satuan_beli`, `harga_per_satuan_beli`). |
| No. rekening & atas nama bank | 20 akun | Sheet **REKENING**. Rekening pencairan 7 toko sudah default 1-1201 Bank BCA — ganti di sheet **TOKO** bila berbeda. |
| HPP | 26 model | Otomatis dihitung ulang setelah harga material & BOM terisi (tombol "Terapkan & Hitung HPP"). |
| Techpack, foto, SOP | 104 | Portal RnD → Style → unggah per model (Papan Kelengkapan Data di Dashboard RnD menunjukkan sisa). |
| Saldo awal (Neraca) | — | Portal Keuangan → Master Akuntansi → **Saldo Awal** (unggah Excel). |
| Pencairan marketplace | — | Portal Keuangan → **Saldo & Pencairan Marketplace**: Tahap 1 impor laporan Penghasilan/Settlement, Tahap 2 impor laporan penarikan. |

## Catatan
- `restore-snapshot` MENIMPA seluruh DB VPS (backup otomatis dibuat dulu di `deploy/backups/`).
- Folder `uploads/` (foto/tech pack) di preview kosong untuk data klien — tidak perlu dipindahkan.
- Jangan jalankan `golive.sh reset/apply` setelah restore-snapshot — snapshot sudah berisi hasil impor Excel.

## 5. Skrip final khusus VPS srv1957551 (hasil inspeksi 2026-09-14)
Kondisi: `/opt/dahost` (compose `dahost`, DB `dahost_erp`, 0 transaksi nyata) + proyek lain `kn-*` (`/opt/kainnusantara`, mongo sendiri) → **Jalur A**.
```bash
# di laptop
scp dahost_snapshot_2026-09-13.archive.gz root@187.77.116.148:/opt/dahost/deploy/golive/
# di VPS (setelah Save to GitHub)
ssh root@187.77.116.148
cd /opt/dahost && git fetch origin main && git checkout origin/main -- deploy/vps_timpa_snapshot.sh
bash deploy/vps_timpa_snapshot.sh dahost_snapshot_2026-09-13.archive.gz
```
Skrip: pagar pengaman (remote/proyek/DB/container harus dahost) → simpan perubahan lokal git (1 berkas) → backup DB →
simpan sandi user/kreator VPS → `update.sh` → kembalikan perubahan lokal (Caddyfile → restart caddy) → mongorestore
`test_database → dahost_erp` → kembalikan sandi → restart backend → 3 gate. Container `kn-*` tidak disentuh.
