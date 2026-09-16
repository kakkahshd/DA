"""scripts/master_template_spec.py — SATU sumber definisi kolom template master.

Dipakai BERSAMA oleh `master_template_generate.py` (membuat berkas Excel) dan
`import_master_template.py` (membaca & memvalidasinya). Kalau dua berkas itu punya
daftar kolom masing-masing, template dan importir pasti berbeda diam-diam suatu hari.

Aturan template:
* Baris pertama = **nama kolom kanonik** (jangan diubah/ditukar urutannya bebas, importir
  mencari berdasarkan NAMA kolom, bukan posisi).
* Baris yang sel pertamanya dimulai `#` = **contoh/komentar** ⇒ DILEWATI importir.
* Kolom bertanda `*` pada PETUNJUK = wajib.
"""
from __future__ import annotations

# (nama_kolom, wajib?, keterangan, contoh)
SHEETS: dict[str, dict] = {
    "01_LOKASI": {
        "collection": "rahaza_locations",
        "judul": "Lokasi kerja & gudang",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode unik lokasi", "GD-UTAMA"),
            ("nama", True, "Nama lokasi", "Gudang Utama"),
            ("tipe", True, "gudang | kantor | produksi | toko", "gudang"),
            ("kode_induk", False, "Kode lokasi induk (opsional)", ""),
            ("aktif", False, "ya | tidak (bawaan: ya)", "ya"),
            ("peran", False, "fg | kain | aksesoris | sample | karantina | cutting | sewing | qc | packing — "
                             "kosong = lokasi kerja biasa; satu peran hanya untuk SATU lokasi", ""),
        ],
    },
    "02_KARYAWAN": {
        "collection": "rahaza_employees",
        "judul": "Karyawan + skema upah (payroll)",
        "kunci": "kode_karyawan",
        "kolom": [
            ("kode_karyawan", True, "Kode internal unik, BUKAN NIK KTP 16 digit; alias lama nik diterima", "EMP-001"),
            ("nama", True, "Nama lengkap", "Siti Aminah"),
            ("jabatan", False, "Petunjuk peran: penjahit | qc | packing | admin | livehost | staff", "penjahit"),
            ("telepon", False, "Nomor HP", "081200000001"),
            ("tanggal_masuk", False, "YYYY-MM-DD", "2024-03-01"),
            ("kode_lokasi", False, "Kode dari sheet 01_LOKASI", "GD-UTAMA"),
            ("skema_upah", False, "bulanan | borongan | harian (bawaan: bulanan)", "borongan"),
            ("gaji_pokok", False, "Rp/bulan (skema bulanan) atau Rp/hari (harian)", "0"),
            ("tarif_lembur_per_jam", False, "Rp/jam", "0"),
            ("aktif", False, "ya | tidak", "ya"),
        ],
    },
    "03_WARNA": {
        "collection": "rahaza_colors",
        "judul": "Master warna (dipakai SKU: STYLE-WARNA-UKURAN)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode warna alfanumerik, jadi bagian SKU", "NVY"),
            ("nama", True, "Nama warna", "Navy"),
            ("hex", False, "Kode warna layar, mis. #1B2A4A", "#1B2A4A"),
            ("urutan", False, "Angka urutan tampil", "1"),
        ],
    },
    "04_UKURAN": {
        "collection": "rahaza_sizes",
        "judul": "Master ukuran (kode WAJIB alfanumerik — ikut menyusun SKU)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Tanpa spasi/garis miring: M, XL, 2XL, ALLSIZE", "2XL"),
            ("nama", True, "Tulisan aslinya boleh bebas: '2XL', 'All Size', '28/30'", "2XL"),
            ("urutan", False, "Angka urutan tampil", "5"),
        ],
    },
    "05_PROSES": {
        "collection": "rahaza_processes",
        "judul": "Proses produksi (dipakai upah borongan per pcs)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode proses", "JAHIT"),
            ("nama", True, "Nama proses", "Jahit"),
            ("urutan", False, "Urutan tahapan", "2"),
            ("permak", False, "ya bila proses perbaikan/rework", "tidak"),
            ("keterangan", False, "Catatan", ""),
        ],
    },
    "06_MATERIAL_KAIN": {
        "collection": "rahaza_materials",
        "judul": "Kain & benang (bahan utama)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode bahan (unik)", "KN-CTN-NVY"),
            ("nama", True, "Nama bahan", "Kain Cotton Combed 30s Navy"),
            ("jenis", True, "fabric (kain) | yarn (benang)", "fabric"),
            ("satuan_dasar", True, "kg | m | yard | roll — SATUAN PENYIMPANAN STOK", "kg"),
            ("komposisi", False, "mis. cotton 100%", "cotton 100%"),
            ("warna", False, "Nama warna bahan", "Navy"),
            ("gramasi_gsm", False, "Angka GSM (kain)", "180"),
            ("lebar_cm", False, "Lebar kain (cm)", "160"),
            ("harga_per_satuan", False, "Rp per satuan dasar (HPP awal)", "95000"),
            ("stok_minimum", False, "Ambang peringatan stok", "50"),
        ],
    },
    "07_AKSESORIS": {
        "collection": "rahaza_materials",
        "judul": "Aksesoris (kancing, label, hangtag, benang jahit, dll) — IKUT DIPAKAI BOM",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode aksesoris (unik)", "ACC-BTN-12"),
            ("nama", True, "Nama aksesoris", "Kancing bulat plastik 12mm"),
            ("satuan_dasar", True, "pcs | gross | pack | m | gram", "pcs"),
            ("kategori", False, "Kelompok: Kancing, Label, Hangtag, Benang Jahit…", "Kancing"),
            ("harga_per_satuan", False, "Rp per satuan dasar", "150"),
            ("stok_minimum", False, "Ambang peringatan stok", "1000"),
            ("satuan_kemasan", False, "Nama kemasan beli: pack | gross | karton", "pack"),
            ("isi_per_kemasan", False, "Berapa satuan dasar per kemasan", "144"),
        ],
    },
    "08_MODEL": {
        "collection": "rahaza_models",
        "judul": "Model/style produk (induk dari SKU & BOM)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode model/style — jadi awalan SKU", "DA-TS01"),
            ("nama", True, "Nama model", "Kaos Basic DA"),
            ("kategori", False, "Kelompok produk", "Kaos"),
            ("keterangan", False, "Catatan", ""),
            ("harga_jual_dasar", False, "Rp harga jual acuan (boleh 0)", "89000"),
        ],
    },
    "09_BARANG_JADI": {
        "collection": "rahaza_materials",
        "judul": "SKU barang jadi (varian model × warna × ukuran)",
        "kunci": "sku",
        "kolom": [
            ("sku", True, "Disarankan MODEL-WARNA-UKURAN", "DA-TS01-NVY-M"),
            ("nama", True, "Nama tampil", "Kaos Basic DA [Navy · M]"),
            ("kode_model", True, "Kode dari 08_MODEL", "DA-TS01"),
            ("kode_warna", True, "Kode dari 03_WARNA", "NVY"),
            ("kode_ukuran", True, "Kode dari 04_UKURAN", "M"),
            ("satuan", False, "Bawaan: pcs", "pcs"),
            ("berat_gram", False, "Berat kirim (gram)", "220"),
            ("harga_jual", False, "Rp harga jual master", "89000"),
            ("stok_minimum", False, "Ambang peringatan", "10"),
        ],
    },
    "10_BOM": {
        "collection": "rahaza_boms",
        "judul": "BOM per model+ukuran+warna opsional — kain, benang, DAN aksesoris",
        "kunci": "kode_model+kode_ukuran+kode_warna+kode_material",
        "kolom": [
            ("kode_model", True, "Kode dari 08_MODEL", "DA-TS01"),
            ("kode_ukuran", True, "Kode dari 04_UKURAN", "M"),
            ("kode_material", True, "Kode dari 06_MATERIAL_KAIN atau 07_AKSESORIS", "KN-CTN-NVY"),
            ("qty_per_pcs", True, "Pemakaian per 1 pcs barang jadi", "0.24"),
            ("satuan", False, "Kosong = satuan stok; sedimensi dikonversi; cm→kg wajib GSM & lebar", "kg"),
            ("keterangan", False, "Catatan baris BOM", "badan"),
            ("kode_warna", False, "Kode 03_WARNA; kosong = BOM umum, terisi = khusus warna ini", ""),
        ],
    },
    "11_VENDOR_CMT": {
        "collection": "vendor_partners",
        "judul": "Vendor CMT / penjahit mitra",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode vendor", "CMT-001"),
            ("nama", True, "Nama vendor/penjahit", "CMT Pak Aan"),
            ("nama_kontak", False, "PIC", "Aan"),
            ("telepon", False, "Nomor HP", "081300000001"),
            ("alamat", False, "Alamat", "Bandung"),
            ("kapasitas_pcs", False, "Kapasitas per bulan (pcs)", "3000"),
            ("keterangan", False, "Catatan", ""),
        ],
    },
    "12_KLIEN_MAKLON": {
        "collection": "dewi_maklon_clients",
        "judul": "Klien maklon (pemberi order)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode klien", "MK-001"),
            ("nama", True, "Nama klien/brand", "Koh Tri (SnBM)"),
            ("nama_kontak", False, "PIC", "Tri"),
            ("telepon", False, "Nomor HP", "081400000001"),
            ("alamat", False, "Alamat", "Jakarta"),
            ("keterangan", False, "Catatan", ""),
        ],
    },
    "13_AKUN_TOKO": {
        "collection": "marketing_platform_accounts",
        "judul": "Akun marketplace / toko online",
        "kunci": "kode_akun",
        "kolom": [
            ("kode_akun", True, "Kode unik akun", "SHP-DALUNA"),
            ("nama_akun", True, "Nama toko seperti di platform", "Shopee Daluna"),
            ("platform", True, "shopee | tiktok | tokopedia | lazada | instagram | facebook", "shopee"),
            ("username", False, "Username/handle toko", "daluna.official"),
            ("grup", False, "Pengelompokan internal", "Daluna"),
            ("status", False, "active | inactive", "active"),
        ],
    },
    "14_KATALOG_JUAL": {
        "collection": "marketing_catalog_items",
        "judul": "Katalog jual per toko (harga jual per SKU per akun)",
        "kunci": "kode_akun+sku",
        "kolom": [
            ("kode_akun", True, "Kode dari 13_AKUN_TOKO", "SHP-DALUNA"),
            ("sku", True, "SKU dari 09_BARANG_JADI", "DA-TS01-NVY-M"),
            ("harga_jual", True, "Rp harga tayang di toko", "99000"),
            ("harga_coret", False, "Rp harga sebelum diskon", "129000"),
            ("tautan_produk", False, "URL produk di platform", ""),
            ("aktif", False, "ya | tidak", "ya"),
        ],
    },
    "15_KOL_KREATOR": {
        "collection": "marketing_kol_creators",
        "judul": "KOL / kreator (tanpa password — akun portal dibuat dari layar Marketing)",
        "kunci": "kode_kreator",
        "kolom": [
            ("kode_kreator", True, "Kode unik kreator", "KOL-001"),
            ("nama", True, "Nama kreator", "Rina"),
            ("tipe", True, "new | kontrak | continue", "kontrak"),
            ("domisili", False, "Kota/daerah", "Bandung"),
            ("telepon", False, "Nomor HP", "081500000001"),
            ("email_portal", False, "Email untuk login portal kreator", "rina@kreator.id"),
            ("kode_akun_toko", False, "Kode akun toko yang dipegang, pisahkan koma", "SHP-DALUNA"),
            ("insentif_mode", False, "none | per_pcs | target_bonus | both", "per_pcs"),
            ("insentif_per_pcs", False, "Rp per pcs terjual", "2000"),
            ("target_pcs", False, "Target pcs per periode", "500"),
            ("bonus_target", False, "Rp bonus bila target tercapai", "500000"),
            ("periode_bulan", False, "Panjang periode insentif (bawaan 3)", "3"),
        ],
    },
    "16_LIVEHOST": {
        "collection": "marketing_livehosts",
        "judul": "Host live (digaji BULANAN lewat payroll HR — wajib tertaut karyawan)",
        "kunci": "email",
        "kolom": [
            ("nama", True, "Nama host", "Ayu"),
            ("email", True, "Email login portal livehost", "ayu@dewiaditya.id"),
            ("kode_karyawan", True, "Kode internal dari 02_KARYAWAN; BUKAN NIK KTP; alias nik_karyawan diterima", "EMP-010"),
            ("telepon", False, "Nomor HP", "081600000001"),
            ("kode_akun_toko", False, "Akun toko yang dilayani, pisahkan koma", "SHP-DALUNA"),
            ("status", False, "active | inactive", "active"),
        ],
    },
    "17_USER": {
        "collection": "users",
        "judul": "Akun login sistem (TANPA kata sandi — sandi awal dibuat sistem, wajib diganti saat login pertama)",
        "kunci": "email",
        "kolom": [
            ("email", True, "Email login (kunci; disimpan huruf kecil)", "siti@dewiaditya.id"),
            ("nama", True, "Nama tampil", "Siti Aminah"),
            ("nik_karyawan", True, "Kode internal karyawan dari 02_KARYAWAN (wajib tertaut)", "EMP-001"),
            ("peran", True, "Nama peran terdaftar di sistem (mis. hr, accounting, admin_gudang)", "hr"),
            ("status", False, "active | inactive", "active"),
            ("keterangan", False, "Catatan (tidak disimpan ke akun)", ""),
        ],
    },
    "18_TUNJANGAN": {
        "collection": "da_payroll_allowances",
        "judul": "Komponen gaji di luar gaji pokok (tunjangan/insentif)",
        "kunci": "kode",
        "kolom": [
            ("kode", True, "Kode unik tunjangan", "TJ-JAB"),
            ("nama", True, "Nama tunjangan", "Tunjangan Jabatan"),
            ("nominal", True, "Rp (atau persen bila cara_hitung percentage_gross)", "100000"),
            ("cara_hitung", True, "fixed | percentage_gross | per_day_attendance | per_hour_worked", "fixed"),
            ("upah_tetap", False, "ya bila termasuk dasar iuran BPJS (upah tetap)", "ya"),
            ("berlaku_untuk", False, "semua | departemen | karyawan (bawaan: semua)", "karyawan"),
            ("departemen", False, "Nama departemen bila berlaku_untuk = departemen", ""),
            ("nik_karyawan", False, "Kode karyawan dari 02_KARYAWAN, pisahkan koma (bila berlaku_untuk = karyawan)",
             "EMP-001,EMP-002"),
            ("keterangan", False, "Catatan", ""),
        ],
    },
}

URUTAN = list(SHEETS.keys())

ENUMS = {
    "tipe lokasi": "gudang · kantor · produksi · toko",
    "jenis material": "fabric (kain) · yarn (benang) · accessory (aksesoris) · fg (barang jadi)",
    "satuan dasar": "pcs · kg · gram · m · yard · roll · pack · gross · lusin",
    "skema upah": "bulanan · borongan · harian",
    "platform": "shopee · tiktok · tokopedia · lazada · instagram · facebook",
    "tipe kreator": "new (belum dapat insentif) · kontrak · continue",
    "insentif mode": "none · per_pcs · target_bonus · both",
    "peran lokasi": "fg · kain · aksesoris · sample · karantina · cutting · sewing · qc · packing",
    "cara hitung tunjangan": "fixed · percentage_gross · per_day_attendance · per_hour_worked",
    "berlaku untuk": "semua · departemen · karyawan",
    "ya/tidak": "ya · tidak (kosong = ya)",
}
