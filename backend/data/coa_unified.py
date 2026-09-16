"""data.coa_unified — BAGAN AKUN TUNGGAL 4 DIGIT (keputusan owner 2026-09-12).

Satu skema saja: `X-XXXX` (1 Aset · 2 Liabilitas · 3 Ekuitas · 4 Pendapatan · 5 HPP ·
6 Beban Operasional · 7 Pendapatan/Beban Lain). Akun khas CV. Dewi Aditya yang dulu
hidup di skema 3 digit (`1-131 Bank BCA – DA Official`, `4-111 Penjualan – Shopee …`,
`7-120 Biaya Vendor CMT – Maklon`) DIPINDAHKAN ke kode 4 digit di bawah induk yang
benar — detailnya TIDAK dilebur (14 rekening bank, 5 dompet digital, pendapatan per
toko, HPP maklon tetap terpisah).

`DA_UNIFIED_ACCOUNTS`  : akun tambahan DA (4 digit) di atas SEED_TEMPLATE kanonik.
`LEGACY_TO_UNIFIED`    : kode 3 digit lama → kode 4 digit (dipakai migrasi & remap referensi).
Kolom: (code, name, type, is_group, parent_code, normal_balance_override, cash_flow_group)
cash_flow_group: OPR (operasi) · INV (investasi) · PND (pendanaan) · None (bukan akun kas/neraca)
"""

DA_UNIFIED_ACCOUNTS = [
    # ── 1 ASET ────────────────────────────────────────────────────────────────
    ("1-1210", "Bank BCA – Entitas & Perorangan", "ASSET", True, "1-1200", None, "OPR"),
    ("1-1211", "Bank BCA – CV Dekka Karya Utama", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1212", "Bank BCA – CV Dzaki Karya Utama", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1213", "Bank BCA – CV Sukma Mitra Utama", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1214", "Bank BCA – Aditya Sulistyo DW (CMT)", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1215", "Bank BCA – Dewi Ratnasari", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1219", "Bank BCA – Lainnya", "ASSET", False, "1-1210", None, "OPR"),
    ("1-1220", "Bank BRI", "ASSET", True, "1-1200", None, "OPR"),
    ("1-1221", "Bank BRI – CV DA Official", "ASSET", False, "1-1220", None, "OPR"),
    ("1-1222", "Bank BRI – CV Dekka Karya Utama", "ASSET", False, "1-1220", None, "OPR"),
    ("1-1223", "Bank BRI – CV Dzaki Karya Utama", "ASSET", False, "1-1220", None, "OPR"),
    ("1-1224", "Bank BRI – CV Sukma Mitra Utama", "ASSET", False, "1-1220", None, "OPR"),
    ("1-1225", "Bank BRI – Hadi Supardi KBB", "ASSET", False, "1-1220", None, "OPR"),
    ("1-1250", "Dompet Digital", "ASSET", True, "1-1200", None, "OPR"),
    ("1-1251", "GoPay", "ASSET", False, "1-1250", None, "OPR"),
    ("1-1252", "DANA", "ASSET", False, "1-1250", None, "OPR"),
    ("1-1253", "DANA – Lain-lain", "ASSET", False, "1-1250", None, "OPR"),
    ("1-1254", "ShopeePay", "ASSET", False, "1-1250", None, "OPR"),
    ("1-1255", "Flazz BCA", "ASSET", False, "1-1250", None, "OPR"),
    ("1-1305", "Piutang Usaha — Maklon", "ASSET", False, "1-1300", None, "OPR"),
    ("1-1405", "Persediaan Barang Jadi — Maklon", "ASSET", False, "1-1400", None, "OPR"),
    ("1-1630", "Uang Muka Pembelian Bahan", "ASSET", False, "1-1600", None, "OPR"),
    ("1-1640", "Uang Muka Vendor CMT", "ASSET", False, "1-1600", None, "OPR"),
    ("1-1650", "Sewa Dibayar Dimuka", "ASSET", False, "1-1600", None, "OPR"),
    ("1-1660", "Deposit Sewa", "ASSET", False, "1-1600", None, "OPR"),
    ("1-2600", "Bangunan Dalam Proses", "ASSET", False, "1-2000", None, "INV"),
    # ── 2 LIABILITAS ─────────────────────────────────────────────────────────
    ("2-1110", "Hutang Vendor CMT (Termin)", "LIABILITY", False, "2-1000", None, "OPR"),
    ("2-1120", "Hutang Ekspedisi & Logistik", "LIABILITY", False, "2-1000", None, "OPR"),
    ("2-1210", "Hutang Bonus Karyawan", "LIABILITY", False, "2-1000", None, "OPR"),
    ("2-1501", "Hutang BPJS Kesehatan", "LIABILITY", False, "2-1000", None, "OPR"),
    ("2-1502", "Hutang BPJS Ketenagakerjaan", "LIABILITY", False, "2-1000", None, "OPR"),
    ("2-1610", "Hutang Angsuran Kendaraan / Inventaris", "LIABILITY", False, "2-1000", None, "PND"),
    ("2-2101", "Hutang Bank – Kredit Lokal (3921555545)", "LIABILITY", False, "2-2000", None, "PND"),
    ("2-2102", "Hutang Bank – Kredit Lokal (3923445567)", "LIABILITY", False, "2-2000", None, "PND"),
    # ── 4 PENDAPATAN ─────────────────────────────────────────────────────────
    ("4-1110", "Penjualan Online Shop – Shopee", "REVENUE", True, "4-1000", None, None),
    ("4-1111", "Penjualan – Shopee Grosirhijabsragen", "REVENUE", False, "4-1110", None, None),
    ("4-1112", "Penjualan – Shopee Daluna", "REVENUE", False, "4-1110", None, None),
    ("4-1113", "Penjualan – Shopee Moen", "REVENUE", False, "4-1110", None, None),
    ("4-1114", "Penjualan – Shopee Lain-lain", "REVENUE", False, "4-1110", None, None),
    ("4-1120", "Penjualan Online Shop – TikTok", "REVENUE", True, "4-1000", None, None),
    ("4-1121", "Penjualan – TikTok Daluna", "REVENUE", False, "4-1120", None, None),
    ("4-1122", "Penjualan – TikTok Outfit Boutique", "REVENUE", False, "4-1120", None, None),
    ("4-1123", "Penjualan – TikTok Style by Moen", "REVENUE", False, "4-1120", None, None),
    ("4-1124", "Penjualan – TikTok Fatimahijab", "REVENUE", False, "4-1120", None, None),
    ("4-1125", "Penjualan – TikTok Dezza Kids", "REVENUE", False, "4-1120", None, None),
    ("4-1126", "Penjualan – TikTok Lain-lain", "REVENUE", False, "4-1120", None, None),
    ("4-1130", "Penjualan Online Shop – Tokopedia", "REVENUE", True, "4-1000", None, None),
    ("4-1131", "Penjualan – Tokopedia", "REVENUE", False, "4-1130", None, None),
    ("4-1400", "Potongan Platform (Fee Shopee/TikTok)", "REVENUE", False, "4-1000", "DEBIT", None),
    ("4-1500", "Pendapatan Maklon", "REVENUE", True, "4-1000", None, None),
    ("4-1510", "Pendapatan Maklon – SnBm", "REVENUE", False, "4-1500", None, None),
    ("4-1520", "Pendapatan Maklon – Klien Lain-lain", "REVENUE", False, "4-1500", None, None),
    ("4-1590", "Retur / Potongan Maklon", "REVENUE", False, "4-1500", "DEBIT", None),
    ("4-9100", "Pendapatan di Luar Usaha Lainnya", "OTHER_INCOME", False, "4-0000", None, None),
    # ── 5 HPP ────────────────────────────────────────────────────────────────
    ("5-1100", "Pemakaian Bahan Baku (Kain / Potongan)", "COGS", False, "5-0000", None, None),
    ("5-1200", "Pemakaian Bahan Pembantu (Aksesori)", "COGS", False, "5-0000", None, None),
    ("5-1300", "Biaya Ekspedisi Bahan Baku", "COGS", False, "5-0000", None, None),
    ("5-2100", "Biaya Vendor CMT – Cutting", "COGS", False, "5-0000", None, None),
    ("5-2200", "Biaya Vendor CMT – Jahit", "COGS", False, "5-0000", None, None),
    ("5-3110", "Listrik – Unit Usaha Lain", "COGS", False, "5-3000", None, None),
    ("5-3120", "Telpon & Internet – Operasional Produksi", "COGS", False, "5-3000", None, None),
    ("5-3600", "Gaji Karyawan Gudang / Produksi", "COGS", False, "5-3000", None, None),
    ("5-3610", "Tunjangan Kesehatan Karyawan Gudang", "COGS", False, "5-3000", None, None),
    ("5-3620", "Bonus Komisi Karyawan Gudang", "COGS", False, "5-3000", None, None),
    ("5-4000", "HPP Proyek Maklon", "COGS", True, "5-0000", None, None),
    ("5-4100", "Biaya Bahan Klien Maklon", "COGS", False, "5-4000", None, None),
    ("5-4200", "Biaya Vendor CMT – Maklon", "COGS", False, "5-4000", None, None),
    ("5-4300", "Biaya Pengiriman ke Klien Maklon", "COGS", False, "5-4000", None, None),
    ("5-4400", "Biaya Administrasi Maklon", "COGS", False, "5-4000", None, None),
    # ── 6 BEBAN OPERASIONAL ──────────────────────────────────────────────────
    ("6-1110", "Biaya Iklan TikTok Ads", "EXPENSE", False, "6-1100", None, None),
    ("6-1111", "Biaya Iklan Facebook / Meta Ads", "EXPENSE", False, "6-1100", None, None),
    ("6-1112", "Biaya Iklan Shopee Ads", "EXPENSE", False, "6-1100", None, None),
    ("6-1113", "Biaya Iklan Tokopedia Ads", "EXPENSE", False, "6-1100", None, None),
    ("6-1120", "Biaya Endorsement", "EXPENSE", False, "6-1100", None, None),
    ("6-1130", "Biaya Pemasaran Lain-lain", "EXPENSE", False, "6-1100", None, None),
    ("6-1210", "Biaya Ongkir Penjualan (Subsidi Ongkir)", "EXPENSE", False, "6-1200", None, None),
    ("6-1220", "Biaya Penanganan COD", "EXPENSE", False, "6-1200", None, None),
    ("6-1230", "Biaya Retur & Klaim Pengiriman", "EXPENSE", False, "6-1200", None, None),
    ("6-1400", "Kemasan & Perlengkapan Toko", "EXPENSE", True, "6-1000", None, None),
    ("6-1410", "Biaya Plastik & Invoice Packaging", "EXPENSE", False, "6-1400", None, None),
    ("6-1420", "Biaya Perlengkapan Online Shop Lainnya", "EXPENSE", False, "6-1400", None, None),
    ("6-1500", "Admin & Platform Online Shop", "EXPENSE", True, "6-1000", None, None),
    ("6-1510", "Biaya Admin & Tagihan Ekspedisi (JNT)", "EXPENSE", False, "6-1500", None, None),
    ("6-1520", "Biaya Langganan Aplikasi (SaaS/Data)", "EXPENSE", False, "6-1500", None, None),
    ("6-1530", "Biaya Bonus Target Karyawan Online Shop", "EXPENSE", False, "6-1500", None, None),
    ("6-2110", "Gaji Pimpinan / Direksi", "EXPENSE", False, "6-2000", None, None),
    ("6-2710", "Beban Penyusutan – Bangunan", "EXPENSE", False, "6-2000", None, None),
    ("6-2720", "Beban Penyusutan – Kendaraan", "EXPENSE", False, "6-2000", None, None),
    ("6-2730", "Beban Penyusutan – Peralatan Kantor", "EXPENSE", False, "6-2000", None, None),
    ("6-2910", "Biaya Makan & Representasi", "EXPENSE", False, "6-2000", None, None),
    ("6-2920", "Biaya Kesehatan (Non-Tunjangan)", "EXPENSE", False, "6-2000", None, None),
    ("6-2930", "Biaya Sosial & Kegiatan Karyawan", "EXPENSE", False, "6-2000", None, None),
    ("6-2940", "Biaya Pajak & Perizinan", "EXPENSE", False, "6-2000", None, None),
    ("6-4102", "Pajak Bunga Tabungan", "EXPENSE", False, "6-4100", None, None),
    ("6-4103", "Biaya Transfer Antar Bank", "EXPENSE", False, "6-4100", None, None),
    ("6-4104", "Biaya Kartu Kredit / Fasilitas Pinjaman", "EXPENSE", False, "6-4100", None, None),
]

# 3 digit lama → 4 digit tunggal. Header 3 digit → header 4 digit setara.
LEGACY_TO_UNIFIED = {
    # header & aset
    "1-000": "1-0000", "1-100": "1-1000", "1-110": "1-1101", "1-120": "1-1320", "1-130": "1-1200",
    "1-131": "1-1201", "1-132": "1-1211", "1-133": "1-1212", "1-134": "1-1213", "1-135": "1-1214",
    "1-136": "1-1215", "1-137": "1-1219",
    "1-141": "1-1221", "1-142": "1-1222", "1-143": "1-1223", "1-144": "1-1224", "1-145": "1-1225",
    "1-150": "1-1250", "1-151": "1-1251", "1-152": "1-1252", "1-153": "1-1253", "1-154": "1-1254", "1-155": "1-1255",
    "1-200": "1-1300", "1-210": "1-1305", "1-211": "1-1302", "1-220": "1-1303", "1-230": "1-1304",
    "1-300": "1-1400", "1-310": "1-1401", "1-320": "1-1402", "1-330": "1-1403", "1-340": "1-1404", "1-350": "1-1405",
    "1-400": "1-1600", "1-410": "1-1630", "1-420": "1-1640", "1-430": "1-1650", "1-440": "1-1501", "1-450": "1-1620",
    "1-500": "1-2000", "1-510": "1-2100", "1-520": "1-2200", "1-521": "1-2201", "1-530": "1-2400", "1-531": "1-2401",
    "1-540": "1-2300", "1-541": "1-2301", "1-550": "1-2500", "1-551": "1-2501",
    "1-600": "1-2000", "1-610": "1-2600", "1-620": "1-1660",
    # liabilitas & ekuitas
    "2-000": "2-0000", "2-100": "2-1000", "2-110": "2-1100", "2-111": "2-1100", "2-112": "2-1110", "2-113": "2-1120",
    "2-120": "2-1200", "2-121": "2-1210", "2-122": "2-1501", "2-123": "2-1502",
    "2-130": "2-1400", "2-131": "2-1301", "2-132": "2-1302", "2-133": "2-1303",
    "2-140": "2-1700", "2-150": "2-1610", "2-160": "2-1600",
    "2-200": "2-2000", "2-210": "2-2101", "2-211": "2-2102", "2-220": "2-2100",
    "3-000": "3-0000", "3-100": "3-1000", "3-200": "3-2000", "3-300": "3-3000", "3-400": "3-4000",
    # pendapatan
    "4-000": "4-0000", "4-100": "4-1000",
    "4-111": "4-1111", "4-112": "4-1112", "4-113": "4-1113", "4-114": "4-1114",
    "4-121": "4-1121", "4-122": "4-1122", "4-123": "4-1123", "4-124": "4-1124", "4-125": "4-1125", "4-126": "4-1126",
    "4-131": "4-1131", "4-140": "4-1200", "4-141": "4-1400",
    "4-200": "4-1500", "4-210": "4-1510", "4-220": "4-1520", "4-230": "4-1590",
    "4-900": "4-9000", "4-910": "4-2100", "4-920": "4-9100",
    # HPP (akun periodik persediaan awal/akhir TIDAK dipakai — sistem perpetual)
    "5-000": "5-0000", "5-100": "5-1000", "5-110": "5-1000", "5-120": "5-1000", "5-130": "5-1000",
    "5-200": "5-1000", "5-210": "5-1100", "5-220": "5-1200", "5-230": "5-2100", "5-231": "5-2200",
    "5-240": "5-1300", "5-250": "5-3000", "5-260": "5-3000",
    # beban online shop
    "6-000": "6-1000", "6-100": "6-1100", "6-110": "6-1110", "6-111": "6-1111", "6-112": "6-1112", "6-113": "6-1113",
    "6-120": "6-1120", "6-130": "6-1130",
    "6-200": "6-1200", "6-210": "6-1210", "6-220": "6-1220", "6-230": "6-1230",
    "6-300": "6-1400", "6-310": "6-1410", "6-320": "6-1420",
    "6-400": "6-1500", "6-410": "6-1510", "6-420": "6-1520", "6-430": "6-1530",
    # maklon
    "7-000": "5-4000", "7-100": "5-4000", "7-110": "5-4100", "7-120": "5-4200", "7-130": "5-4300", "7-140": "5-4400",
    # overhead produksi
    "8-000": "5-3000", "8-100": "5-3000", "8-110": "5-3600", "8-111": "5-3610", "8-112": "5-3620",
    "8-200": "5-3000", "8-210": "5-3100", "8-220": "5-3110", "8-230": "5-3120",
    "8-300": "6-2700", "8-310": "6-2710", "8-320": "5-3200", "8-330": "6-2720", "8-340": "6-2730",
    # umum & administrasi
    "9-000": "6-2000", "9-100": "6-2000", "9-110": "6-2110", "9-120": "6-2100", "9-130": "6-3100",
    "9-200": "6-2000", "9-210": "6-2400", "9-220": "6-2500", "9-230": "6-2200", "9-240": "6-2300",
    "9-250": "6-3400", "9-260": "6-2910", "9-270": "6-2920", "9-280": "6-2930", "9-290": "6-2900",
    "9-300": "6-4100", "9-310": "6-4101", "9-320": "7-2000", "9-330": "6-4102", "9-340": "6-4103", "9-350": "6-4104",
    "9-400": "6-2900", "9-410": "6-2940", "9-420": "7-4000",
}

# Akun kanonik yang WAJIB berstatus header (induk anak-anak baru)
# (5-1000 · 5-2000 · 4-9000 · 6-4100 TETAP postable — dirujuk profil posting; anak barunya jadi saudara)
UNIFIED_GROUP_CODES = {"1-1200", "1-1300", "1-1400", "1-1600", "1-2000", "2-1000", "2-2000",
                       "4-1000", "5-0000", "5-3000", "6-1000", "6-1100", "6-1200", "6-2000"}


def unified_code(code: str) -> str:
    """Kode apa pun → kode 4 digit tunggal (kode 4 digit dikembalikan apa adanya)."""
    if not code:
        return code
    base, _, suffix = code.partition("-")
    if len(code.split("-")) >= 2 and len(code.split("-")[1]) == 3:
        head = "-".join(code.split("-")[:2])
        mapped = LEGACY_TO_UNIFIED.get(head)
        if mapped:
            rest = code[len(head):]
            return mapped + rest
    return code
