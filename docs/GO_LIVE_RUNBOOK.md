# RUNBOOK GO-LIVE DATA NYATA — CV. Dewi Aditya (VPS)

Disusun 2026-09-06 setelah seluruh langkah diuji di lingkungan preview
(reset → impor `--apply` → impor ulang idempoten → login akun baru → ganti sandi).

## Keputusan owner yang dikodekan
| Perkara | Keputusan |
|---|---|
| Cakupan reset | Semua koleksi dikosongkan KECUALI: `users` (hanya superadmin), `roles`, `role_permissions`, COA + posting profiles, `company_settings`, `wh_unit_master`/`wh_unit_conversions`, `doc_number_configs`, `pdf_templates`, konfigurasi notifikasi |
| Lokasi bawaan `GED-*/ZNA-*` | **Dimatikan** (`SEED_DEFAULT_LOCATIONS=false`). Kode inti kini mencari lokasi lewat **peran** (`storage_role`) |
| Peran lokasi Excel | `GD-L1-RAK`=fg · `GD-L1-ACC`=aksesoris · `GD-L1-QC`=karantina · `GD-L2-CUT`=cutting · `GD-L2`=kain |
| 12 konflik katalog `DA-4401-*` (85.999 vs 172.999) | **Tidak ditebak** — 24 baris dikeluarkan ke sheet `DAFTAR_PERBAIKAN`, menunggu jawaban klien |
| Sandi awal 25 akun `17_USER` | Satu sandi awal bersama (`MASTER_IMPORT_INITIAL_PASSWORD`, bawaan `Dewi@123`) + **wajib ganti saat login pertama** |
| Superadmin | `admin@garment.com` tidak disentuh |

## Prasyarat di VPS
1. `backend/.env` tambahkan (tanpa komentar):
   ```
   SEED_DEFAULT_LOCATIONS=false
   ALLOW_DEMO_SEED=false
   MASTER_IMPORT_INITIAL_PASSWORD=<sandi awal pilihan Anda>
   ```
2. `mongodump`/`mongorestore` tersedia di server (dipakai skrip reset).
3. Berkas master: `private/golive/MASTER_DATA_DA_GOLIVE.xlsx` (dibuat dari
   `MASTER_DATA_DA_PERBAIKAN_2.xlsx` lewat `scripts/prepare_golive_workbook.py`; berkas asli tidak diubah).

## Urutan eksekusi (jalankan dari folder repo)
```bash
# 0. Gate importir harus hijau (aman dijalankan kapan pun: hanya menyentuh dokumen ber-TAG uji)
python3 scripts/verify_impor_master_template.py

# 1. Inventarisasi data yang ada (read-only)
python3 scripts/audit_data_demo.py --json private/golive/audit_sebelum_reset.json

# 2. Reset: dry-run dulu, lalu eksekusi (mongodump otomatis ke backups/pre_golive_<waktu>/)
python3 scripts/reset_for_golive.py
python3 scripts/reset_for_golive.py --apply          # ketik HAPUS saat diminta
sudo supervisorctl restart backend                    # seed startup: COA/roles/proses, TANPA lokasi bawaan

# 3. Periksa berkas (harus: 0 kesalahan)
python3 scripts/import_master_template.py private/golive/MASTER_DATA_DA_GOLIVE.xlsx

# 4. Simpan, lalu ulangi sekali (uji idempoten: semua angka pindah ke kolom "diperbarui")
python3 scripts/import_master_template.py private/golive/MASTER_DATA_DA_GOLIVE.xlsx --apply
python3 scripts/import_master_template.py private/golive/MASTER_DATA_DA_GOLIVE.xlsx --apply

# 5. Hitung HPP dari layar Costing (Portal Produksi → Costing → Terapkan HPP)
```

## Angka yang harus muncul (impor pertama)
01_LOKASI 11 · 02_KARYAWAN 25 (+25 profil gaji `02_KARYAWAN·profil_gaji`) · 03_WARNA 105 · 04_UKURAN 0 baru/6 diperbarui · 05_PROSES 0/6 ·
06_MATERIAL_KAIN 191 · 07_AKSESORIS 324 · 08_MODEL 104 · 09_BARANG_JADI 355 · **10_BOM 472**
(464 + 8 koreksi owner DA-2101: 465 kg → 0,465 kg) · 11_VENDOR_CMT 10 · 12_KLIEN_MAKLON 1 · 13_AKUN_TOKO 7 ·
**14_KATALOG_JUAL 640 baru + 4 diperbarui** (656 − 12 baris Rp 172.999 yang dibuang atas keputusan owner
2026-09-12: DA-4401-* = Rp 85.999; 4 baris identik) · 15_KOL_KREATOR 9 · 16_LIVEHOST 2 · **17_USER 25** · **18_TUNJANGAN 12**.
Keputusan owner 2026-09-12 lainnya: tarif jahit CMT per model DIBIARKAN kosong — terisi otomatis dari SPK nyata
(`po_items.cmt_price_snapshot`); HPP batch tetap Rp 0 sampai SPK pertama. Sisa DAFTAR_PERBAIKAN (kode kain tak dikenal,
qty BOM kosong, isi kemasan aksesoris) menunggu jawaban klien.
Peringatan ±558 (harga aksesoris 0, BOM tanpa aksesoris, sandi awal) — bukan penghalang.

## Setelah go-live
- Semua 25 akun login dengan sandi awal → layar **"Ganti kata sandi awal"** muncul otomatis; tidak bisa masuk sebelum mengganti.
- 23 email `17_USER` masih USULAN (`nama@dewiaditya.id`) — ganti di berkas + impor ulang **sebelum** dibagikan (email = kunci akun).
- Jawaban klien untuk 24 baris katalog `DA-4401-*` → isi kembali ke `14_KATALOG_JUAL`, impor ulang (idempoten).
- Endpoint seed demo (`/api/seed/maklon-full`, `/api/dewi/seed-demo-full`, `/api/rahaza/hr-seed/*`) menjawab **403** selama `ALLOW_DEMO_SEED=false`.
- `rahaza_sizes` berisi 2 ukuran bawaan tambahan (`STD`, `JMB`) dari seed startup `routes/rahaza_production.py`; tidak dipakai SKU Excel, aman dibiarkan.

## Membatalkan
```bash
mongorestore --uri "$MONGO_URL" --gzip --nsInclude "$DB_NAME.*" --drop backups/pre_golive_<waktu>
```
