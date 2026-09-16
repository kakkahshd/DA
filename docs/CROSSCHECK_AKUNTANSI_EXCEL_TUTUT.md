# CROSSCHECK — Template "Akuntansi Excel Dagang (sampel)" (Tutut) vs Modul Keuangan DA37

Disusun 2026-09-12. Sumber: `private/golive/tutut_akuntansi_dagang_sampel.xlsm` (PT. DAGANG, tahun 2015,
**data contoh** — bukan data CV. Dewi Aditya). Tujuan: memastikan cara kerja yang dikenal akuntan tersedia
di sistem, dan menandai yang belum ada.

## 1. Peta fitur — Excel → Sistem

| Sheet Excel | Fungsi | Di sistem (Portal Keuangan) | Status |
|---|---|---|---|
| **D-Akun** | Daftar akun 3 digit (`1-110 Kas Kecil`), Pos Saldo DB/KR, Group Neraca/LR, Saldo Awal, **Kelompok Arus Kas (OPR/INV/PND)** | Master Akuntansi → Bagan Akun (`rahaza_coa_accounts`, 282 akun aktif) | ✅ Ada, **tetapi**: (a) bagan **campuran 2 skema** — 4 digit kanonik (`1-1201 Bank BCA`) + 111 akun 3 digit aktif (pendapatan per toko Shopee/TikTok, biaya maklon, dll.) + 66 akun 3 digit lama nonaktif; (b) **kolom Kelompok Arus Kas per akun TIDAK ADA**; (c) **Saldo Awal per akun TIDAK ADA** (lihat §2.1) |
| **Akun Ptg** | Setting akun penting (KAS, PIUTANG, HUTANG, Persediaan AWAL/AKHIR, REKON, MEMO) | Master Akuntansi → Profil Posting (37 jenis transaksi otomatis) + Auto Akun Subledger + Pemetaan GL | ✅ Lebih lengkap (otomatis per kejadian: invoice, pembayaran, gaji, penyusutan, …) |
| **Jurnal** (Kas Kecil, Bank, Memorial, Rekonsiliasi) | Jurnal per buku kas dengan akun lawan + kode pembantu | Jurnal Umum, Kas & Bank, Kas Kecil, Transfer Bank, Rekonsiliasi Bank | ✅ Ada |
| **N-Lajur** | Neraca lajur: Saldo Awal · Mutasi · Saldo Akhir · kolom LR · kolom Neraca | Laporan Keuangan → **Neraca Lajur** (`/reports/worksheet`, ekspor Excel) | ✅ Ada (2026-09-12) — 10 kolom + baris laba bersih penyeimbang |
| **Neraca**, **Laba-R** | Per bulan, kolom "akum. s/d bulan" | Laporan Keuangan → Neraca, Laba Rugi (rentang tanggal bebas) | ✅ Ada |
| **Arus-K** | Arus kas **direct** dikelompokkan dari **tag akun** OPR/INV/PND | Laporan Keuangan → Arus Kas: dua tampilan — **Per Kategori Mutasi** (kas/bank) dan **Per Akun (OPR/INV/PND)** dari buku besar lewat `cash_flow_group` akun (Bagan Akun) | ✅ Ada (2026-09-12); batas 500 mutasi DIHAPUS (agregasi Mongo); jurnal saldo awal = kas awal |
| **Bk-Besar** | Buku besar per akun dengan saldo berjalan | Laporan Keuangan → Buku Besar | ✅ Ada |
| **D-Pbantu**, **Bk-Pbantu** | Daftar & buku pembantu piutang/hutang per relasi (saldo awal, mutasi, akhir) | Sub-ledger otomatis per pelanggan/supplier/vendor (`1-1301-xxx`), Aging Piutang (AR-360), Aging Hutang | ✅ Ada (bentuk berbeda: per akun sub-ledger + aging) |
| **Aset** | Daftar aset tetap & penyusutan garis lurus per bulan | Aset Tetap + Depresiasi Aset (Batch) + Pelepasan Aset | ✅ Ada |
| **Laba-12**, **Neraca-12** | Laba rugi & neraca **12 kolom bulan** dalam satu tabel | Laporan Keuangan → **Laba Rugi 12 Bln** / **Neraca 12 Bln** (`/reports/profit-loss-monthly`, `/reports/balance-sheet-monthly`, ekspor Excel) | ✅ Ada (2026-09-12) |
| **Laba-Ch**, **Neraca-Ch** | Grafik | Dashboard Keuangan / Rekap Keuangan | ✅ Sebagian |

## 2. Kesenjangan yang penting untuk go-live (urutan dampak)

### 2.1 Saldo Awal Neraca (P0)
Excel mewajibkan kolom **Saldo Awal** per akun sebelum bulan pertama. Sistem hanya punya saldo awal untuk
**akun kas/bank** (Kas & Bank) — **tidak ada alat memasukkan saldo awal neraca lengkap** (piutang, hutang,
persediaan, aset, akumulasi penyusutan, modal, laba ditahan) per tanggal go-live. Tanpa ini Neraca sistem
tidak akan seimbang dengan pembukuan lama.
→ Usulan: layar **"Saldo Awal Go-Live"** (Master Akuntansi): tabel akun neraca, isi debit/kredit, sistem
memeriksa D = K, lalu memposting **satu jurnal pembuka** (`opening_balance`) yang terkunci; bisa impor dari
kolom Saldo Awal template Excel (format D-Akun) dan sub-ledger piutang/hutang per relasi (format D-Pbantu).

### 2.2 Bagan akun campuran 3 digit / 4 digit (P1)
Akuntan terbiasa `1-110`; sistem kanonik `1-1101`. Dua skema hidup berdampingan → risiko salah pilih akun saat
jurnal manual. → Pilihan: (a) kanonik 4 digit, semua 3 digit disembunyikan dari pemilih akun (tetap ada untuk
histori), atau (b) migrasi kode ke 3 digit ala template. Butuh keputusan owner/akuntan.

### 2.3 Laporan 12 bulan (P1)
Laba Rugi & Neraca 12 kolom per bulan (+ total) — endpoint baru `profit-loss-monthly`, `balance-sheet-monthly`,
tab baru di Laporan Keuangan, ekspor Excel.

### 2.4 Neraca Lajur (P2)
Tampilan Neraca Saldo diperluas: Saldo Awal · Mutasi · Saldo Akhir · **Laba Rugi (D/K)** · **Neraca (D/K)**,
selisih otomatis = laba bersih periode.

### 2.5 Arus Kas (P2)
(a) Perbaiki batas 500 mutasi; (b) tambah **Kelompok Arus Kas per akun** (OPR/INV/PND) di Bagan Akun sebagai
opsi klasifikasi kedua (metode tidak langsung dari jurnal), sehingga tidak bergantung pada kategori mutasi kas.

### 2.6 Kebersihan data (dilakukan hari ini)
8 akun sub-ledger sisa alat uji (`1-1301-001/002`, `1-1303-GATE42-*`, `1-1303-INV*`) dihapus; tidak ada jurnal yang menunjuknya.

## 3. Hal yang TIDAK perlu ditiru dari template
- Persediaan Awal/Akhir sebagai akun HPP (metode periodik dagang). Sistem memakai **perpetual**: HPP lahir per
  pengiriman dari biaya batch (potongan + jahit); persediaan bahan/WIP/FG bergerak otomatis.
- Kode pembantu manual (`PU-001`). Sistem membuat sub-ledger otomatis per pelanggan/supplier/vendor/karyawan.

## 4. Tindak lanjut yang SUDAH dikerjakan (2026-09-12, keputusan owner)
- **Bagan akun tunggal 4 digit** (`backend/data/coa_unified.py`): 105 akun kanonik + 96 akun khas DA (14 rekening bank per
  entitas, 5 dompet digital, penjualan per toko Shopee/TikTok/Tokopedia, pendapatan & HPP maklon, beban online shop,
  overhead produksi) — semua skema 3 digit dihapus/dimigrasi (`LEGACY_TO_UNIFIED`), referensi profil posting, peta akun channel,
  parent sub-ledger, rekening kas/bank, kategori expense, dan konstanta kode di backend ikut diremap. Fresh install
  langsung menyemai skema tunggal; DB lama dimigrasi otomatis saat start (`migrate_coa_canonical`, idempoten, purge legacy tak terpakai).
- Gate **INV-F47** `scripts/verify_coa_unified.py` (K1–K9) HIJAU; ditambahkan ke `gate.sh`.
- **Template & impor Saldo Awal Go-Live**: `python3 scripts/saldo_awal_golive.py template private/golive/SALDO_AWAL_GOLIVE.xlsx`
  (89 akun neraca; sheet rincian piutang/hutang per relasi) → `import <xlsx> --date YYYY-MM-DD [--balance-to-retained] [--apply]`
  memeriksa header/akun/D=K/rincian relasi, memposting SATU jurnal `opening_balance` terkunci. Saat ini semua saldo 0 (keputusan owner).
- **2026-09-12 (lanjutan) — SEMUA kesenjangan §2.1, §2.3, §2.4, §2.5 TUTUP:**
  - Layar **Saldo Awal** (Master Akuntansi → tab Saldo Awal): unduh template → unggah → pratinjau (error per baris, rincian relasi vs akun
    kontrol, D = K, opsi tutup selisih ke 3-2000) → Posting SATU jurnal `opening_balance` terkunci; superadmin bisa membatalkan dengan alasan.
    SSOT `backend/core/opening_balance.py` (dipakai layar & `scripts/saldo_awal_golive.py`).
  - **Laba Rugi 12 Bln** & **Neraca 12 Bln** (tahun kalender Jan–Des, kolom Total & akumulasi, tiap kolom neraca dicek seimbang) + **Neraca Lajur**;
    ekspor Excel `GET /reports/export-xlsx?report=…` memakai perhitungan yang sama dengan layar (`backend/core/fin_statements.py`).
  - **Arus Kas**: batas 500 mutasi dihapus (agregasi Mongo); tampilan **Per Akun (OPR/INV/PND)** dari buku besar; setiap akun kini punya
    `cash_flow_group` (bawaan dari kode: 1-2xxx INV, 2-2xxx & ekuitas PND, lainnya OPR — bisa diubah di Bagan Akun, kolom "Arus Kas").
  - Gate **INV-F48** `scripts/verify_laporan_keuangan_ext.py` (L1–L9, end-to-end, bersih sendiri) HIJAU; ditambahkan ke `gate.sh`.

## 5. Sinkron master ↔ bagan akun (2026-09-12, lanjutan — keputusan owner: "jangan ada duplikasi")
Mesin `backend/core/finance_sync.py` (idempoten; jalan saat start server, `POST /api/rahaza/finance/sync-masters`,
tombol **Sinkron Bagan Akun & GL** di Kas & Bank):
- **Kas & Bank**: 2 kas + 14 bank + 5 dompet di CoA → 20 rekening tertaut (`gl_account_code` = kode akun). Form Tambah
  memilih akun GL yang belum tertaut (`/cash-accounts/gl-candidates`); GL sudah tertaut → 409; rekening kas baru tanpa GL → sub-ledger di 1-1100.
- **Vendor CMT**: Auto Akun `cmt_vendor` → SSOT `vendor_partners`, induk **2-1110 Hutang Vendor CMT (Termin)**; profil posting
  `cmt_ap_invoice.credit_ap` = 2-1110; 10 sub-ledger `2-1110-<kode>`; id lama `dewi_cmt_partners` dipetakan lewat `canonical_id`.
- **Klien maklon**: tipe Auto Akun baru `maklon_client` (induk 1-1305) → `1-1305-KOHTRI-00001`.
- **Toko online (7 toko nyata)**: akun pendapatan per toko di 4-111x/4-112x (dibuat bila belum ada: 4-1115 Outfit Boutique, 4-1116 Rayona,
  4-1117 Sukma, 4-1127 TikTok Rayona; GHS = 4-1111), sub-ledger piutang `1-1303-<kode toko>`, Peta Akun Channel (kunci = kode toko).
  Akun pendapatan toko lama tanpa toko & tanpa jurnal DINONAKTIFKAN (4-1112, 4-1113, 4-1123, 4-1124, 4-1125, 4-1131); "Lain-lain" tetap hidup.
- Gate **INV-F49** `scripts/verify_finance_sync.py` (S1–S9) HIJAU; INV-F47 K2 mengenali penonaktifan oleh finance_sync.
