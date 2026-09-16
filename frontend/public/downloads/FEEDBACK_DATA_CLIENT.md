# Review Data Master Klien — `TEMPLATE MASTER DATA - system.xlsx`
Tanggal review: 2026-09-07 · Alat: `scripts/import_master_template.py` (mode periksa, tidak ada yang disimpan)

## 1. Apakah struktur template masih relevan dengan sistem?
**Ya — 16 sheet dan nama kolomnya masih persis sama dengan definisi sistem saat ini** (`scripts/master_template_spec.py`). Tidak ada kolom yang dihapus/berganti nama sejak template diberikan. Yang berubah hanya **petunjuk** di sheet `00_PETUNJUK` (ditambah daftar kesalahan umum) — template baru yang bersih terlampir: `TEMPLATE_MASTER_DA.xlsx`.

## 2. Hasil pemeriksaan otomatis
| | Jumlah |
|---|---|
| Baris data yang diisi klien | ± 2.350 |
| Baris DITOLAK (harus diperbaiki) | **1.990** |
| Peringatan (tidak menghalangi) | 53 |
| Yang bisa langsung masuk bila sisanya diperbaiki | 301 baris (85 kain, 78 aksesoris, 104 model, 10 BOM, 9 vendor, 7 akun toko, 8 KOL) |

Rincian per baris ada di `REVIEW_DATA_CLIENT.xlsx` (sheet KESALAHAN & PERINGATAN, dengan nomor baris Excel).

## 3. Lima kesalahan yang menyebabkan ~85 % penolakan (perbaiki ini dulu)
1. **Tanda `#` disalin ke kode** — 03_WARNA (`#HTM`, 105 baris), 04_UKURAN (`#M`, `#ALL SIZE`), 09_BARANG_JADI kolom kode_ukuran (381 baris), 11/12 kode vendor & klien. Tanda `#` hanya penanda *baris contoh*. Perbaikan: Find & Replace `#` → kosong pada kolom kode (BUKAN pada kolom `hex`).
2. **Kode ukuran mengandung spasi** — `ALL SIZE` harus `ALLSIZE` (kode ikut membentuk SKU). Ini juga membuat 181 baris BOM ditolak.
3. **09_BARANG_JADI: kolom `kode_warna` diisi NAMA warna** (`MAHOGANY`, `MOCA `) bukan kode dari 03_WARNA (`MHG`, `MCA`); **`kode_model` diisi kategori** (`DRESS`, `BLOUSE`) atau **dikosongkan pada 339 baris lanjutan**; `nama` kosong pada 331 baris. Setiap baris wajib lengkap — tidak ada "isi sekali untuk satu blok".
4. **06_MATERIAL_KAIN: kolom `jenis` kosong (102 baris) atau diisi `Knit`/`Knit palmer` (100 baris)** — nilai sah hanya `fabric` | `yarn` (sistem kini juga menerima `kain`/`knit`/`woven` → fabric, `benang` → yarn; `Knit palmer` tetap tidak sah → tulis `fabric`, taruh "Knit Palmer" di kolom `komposisi`/`nama`).
5. **07_AKSESORIS: `isi_per_kemasan` diisi teks** (`1 karung 60kg`, `4860/6300`, `1 kg`) pada 236 baris — harus angka saja; **`satuan_dasar` ganda** (`m/kg`, `pack/roll`, `m/roll/yard`) pada 14 baris — pilih SATU satuan stok.

## 4. Kesalahan lain yang ditemukan
| Sheet | Temuan | Dampak bila dibiarkan |
|---|---|---|
| Semua | Nama sheet diberi ✅ (`✅01_LOKASI`) | Versi importir lama melewati sheet itu diam-diam; versi baru tetap membaca tapi memberi peringatan |
| 01_LOKASI | `tipe` = `Kantor`, `Aksesoris`, `Area Rak Stok` (harus `gudang|kantor|produksi|toko`); `kode_induk` menunjuk `DA-KTR01`, `DA-GD01` yang tidak ada di sheet | Hierarki lokasi putus |
| 02_KARYAWAN | Hanya berisi teks `DONE`, tidak ada data | 16_LIVEHOST tidak bisa ditautkan → gaji host tidak bisa dihitung |
| 03_WARNA | 6 `hex` kosong, 1 salah (`#p#648052`); 8 nama berakhir spasi (`PUTIH `) | Tampilan warna kosong; spasi dibersihkan otomatis |
| 06_MATERIAL_KAIN | 10 kode kembar (`KN-K24-BRG`, `KN-HRT-ARM`, …); 14 nama warna berakhir spasi; 23 nama warna bahan tidak ada di 03_WARNA | Baris kembar saling menimpa |
| 07_AKSESORIS | 5 kode kembar; 88 harga 0; nama memuat harga/kemasan (`Bisban warna hitam 1 Roll 21,919`) — harga taruh di kolom harga, kemasan di `satuan_kemasan`; kategori tidak konsisten (`kancing`, `kancing 22l 4l`, `kancing 18l 2l`) | HPP 0; pencarian & laporan per kategori berantakan |
| 08_MODEL | 104 model semua `harga_jual_dasar` = 0 (boleh, tapi margin tidak bisa dihitung sampai diisi); 27 nama model dipakai >1 kode (`Mave` = DA-4301 & DA-4302) — pastikan memang varian berbeda | Laporan margin kosong |
| 09_BARANG_JADI | 5 SKU kembar (`DA-1509-BLP-M`, `DA-4301-HTM-M`, …); warna `HITAM POLKA`, `WHITE POLKA`, `PUTIH POLKA` belum ada di 03_WARNA (dan `WHITE` vs `PUTIH` tidak konsisten) | SKU hantu / stok terpecah |
| 10_BOM | 155 `qty_per_pcs` kosong + 36 bukan angka; **371 baris satuan `cm` padahal stok bahan `kg`/`yard`** — sistem TIDAK mengonversi, HPP akan salah; 340 kode material tidak ada di 06/07 (`KN-RMT-DGP`, `KN-K31-NVY`, …); 1 material ganda pada BOM DA-2103/XL | HPP salah atau nol |
| 11_VENDOR_CMT | Kode `0001`, `0007` — aman, tapi pastikan Excel tidak mengubah jadi `1`, `7` | — |
| 12_KLIEN_MAKLON | Hanya 1 baris, kodenya `#KOHTRI-00001` | Klien maklon tidak masuk |
| 14_KATALOG_JUAL | **`harga_jual` dan `harga_coret` tertukar pada 385 baris** (jual 160.000 > coret 107.999; harga coret harus harga SEBELUM diskon); kolom `tautan_produk` dobel (kolom kedua kosong menimpa yang berisi → semua tautan hilang); kolom B tanpa judul berisi `SHP-01`; kolom `nama` tidak dikenal | Harga diskon salah tampil, tautan hilang |
| 15_KOL_KREATOR | `tipe` = `Continue ` (spasi, dibersihkan otomatis); 1 kreator `new` diberi insentif per_pcs (aturan: `new` = belum berhak); telepon jadi angka `81233660017.0` (0 depan hilang — sistem kini memulihkannya, tapi ketik sebagai teks) | Insentif salah |
| 16_LIVEHOST | `nik_karyawan` diisi NIK KTP 16 digit, padahal harus NIK/kode karyawan dari 02_KARYAWAN; `kode_akun_toko` = `SHP 1`, `TTK 3, SHP 3` (harus `SHP-01`, `TTK-03`, `SHP-03`) | Host tidak bisa digaji & tidak tertaut toko |

## 5. Bug/cacat pada IMPORTIR sistem yang ditemukan lewat berkas ini (sudah diperbaiki)
1. Sheet yang diberi hiasan nama (`✅01_LOKASI`) **dilewati diam-diam** → kini dicari secara toleran + peringatan.
2. Kode yang diawali `#` (`#HTM`) **dibuang diam-diam sebagai "baris contoh"** → kini hanya `# ` (pagar + spasi) yang dianggap contoh; kode ber-`#` dilaporkan sebagai kesalahan dengan petunjuk.
3. Judul kolom dobel (`tautan_produk` ×2) **menimpa data tanpa pemberitahuan** → kini kesalahan.
4. Kolom tanpa judul / tidak dikenal → kini peringatan (sebelumnya hilang tanpa jejak).
5. `kode_induk` lokasi yang tidak ada → sebelumnya diam-diam jadi kosong, kini kesalahan.
6. BOM dengan satuan ≠ satuan stok bahan (`cm` vs `kg`) → sebelumnya diterima dan HPP salah, kini kesalahan.
7. `harga_coret` < `harga_jual` → kini kesalahan (indikasi tertukar).
8. `isi_per_kemasan` teks (`1 karung 60kg`) → sebelumnya diam-diam jadi 1, kini kesalahan.
9. Telepon yang diubah Excel jadi angka (`81233660017.0`) → kini dipulihkan menjadi `081233660017`.
10. Sheet kosong / tanpa baris data → kini peringatan.
11. Importir kini bisa menulis laporan Excel (`--report hasil.xlsx`) untuk dikirim balik ke pengisi.

## 6. Langkah yang disarankan
1. Kirim ke klien: `TEMPLATE_MASTER_DA.xlsx` (baru, kosong) + `REVIEW_DATA_CLIENT.xlsx` + bagian 3–4 dokumen ini.
2. Klien memperbaiki **urut dari sheet 01 → 16** (sheet awal menjadi rujukan sheet berikutnya).
3. Jalankan `python3 scripts/import_master_template.py <berkas> --report review.xlsx` sampai **0 kesalahan**, baru `--apply`.
4. Setelah master masuk: hitung ulang HPP dari layar Costing; buat password portal kreator/livehost dari layar Marketing.
