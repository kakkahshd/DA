#!/usr/bin/env python3
"""scripts/import_master_template.py — IMPOR MASTER dari TEMPLATE_MASTER_DA.xlsx.

    python3 scripts/import_master_template.py berkas.xlsx            # PERIKSA saja (dry-run)
    python3 scripts/import_master_template.py berkas.xlsx --apply    # simpan
    python3 scripts/import_master_template.py berkas.xlsx --only 10_BOM,09_BARANG_JADI

PRINSIP
-------
* **Dry-run adalah bawaan.** Menyimpan harus diminta secara sadar (`--apply`).
* **Satu baris salah tidak membatalkan seluruh berkas**, tetapi seluruh KESALAHAN
  dilaporkan lebih dulu dan penyimpanan DITOLAK selama masih ada kesalahan. Impor
  separuh-separuh adalah cara paling cepat melahirkan SKU hantu (kejadian nyata di
  sistem ini: 3 baris SPK dengan SKU yang tidak punya master, Rp 3,6 jt menggantung).
* **Idempoten**: kunci alami (kode/nik/sku/kode_akun) dipakai upsert ⇒ impor ulang
  MEMPERBARUI, tidak menduplikasi.
* **TIDAK menghapus apa pun.** Data lama (termasuk demo) dibiarkan; sesuai keputusan
  pemilik, pembersihan dilakukan di lingkungan produksi masing-masing.
* Yang **tidak** ditangani di sini (dan disebutkan di laporan): password portal
  kreator/livehost, saldo awal stok/piutang/kas, dan varian SSOT RnD.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
import math
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from master_template_spec import SHEETS, URUTAN  # noqa: E402

G, R, Y, C, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"
BATCH = f"master_template_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
ERRORS: list[tuple[str, int, str]] = []
WARNINGS: list[tuple[str, int, str]] = []
STATS: dict[str, dict] = {}
# kolom yang isinya KODE rujukan — awalan '#' di sini hampir pasti salah salin dari baris contoh
REF_COLS = ("kode", "nik", "kode_karyawan", "sku", "kode_akun", "kode_kreator", "kode_model", "kode_warna",
            "kode_ukuran", "kode_material", "kode_induk", "kode_lokasi", "nik_karyawan",
            "kode_akun_toko")
# Sandi awal akun 17_USER (keputusan owner: satu sandi awal bersama + wajib ganti saat login pertama).
INITIAL_PASSWORD_ENV = "MASTER_IMPORT_INITIAL_PASSWORD"
INITIAL_PASSWORD_DEFAULT = "Dewi@123"
PROTECTED_USER_ROLES = ("superadmin",)


def err(sheet: str, row: int, msg: str) -> None:
    ERRORS.append((sheet, row, msg))


def warn(sheet: str, row: int, msg: str) -> None:
    WARNINGS.append((sheet, row, msg))


def _norm_sheet(name: str) -> str:
    return "".join(ch for ch in s(name).upper() if ch.isalnum() or ch == "_")


def resolve_sheet(wb, name: str):
    """Cari sheet walau namanya diberi hiasan (mis. '✅01_LOKASI', '01_LOKASI (done)')."""
    if name in wb.sheetnames:
        return name
    for n in wb.sheetnames:
        if _norm_sheet(n).startswith(_norm_sheet(name)) or _norm_sheet(n).endswith(_norm_sheet(name)):
            warn(name, 0, f"nama sheet '{n}' tidak persis '{name}' — tetap dibaca; "
                          "sebaiknya kembalikan ke nama aslinya")
            return n
    return None


def phone(v) -> str:
    """Excel sering mengubah '081234' menjadi angka 81234.0 — pulihkan sebagai teks."""
    t = s(v)
    if t.endswith(".0"):
        t = t[:-2]
    if t.isdigit() and t.startswith("8") and len(t) >= 9:
        t = "0" + t
    return t


def now():
    return datetime.now(timezone.utc)


def s(v) -> str:
    return "" if v is None else str(v).strip()


def _num_text(v) -> str:
    """Normalisasi teks angka gaya Indonesia: 'Rp 95.000' → '95000', '0,24' → '0.24'.
    Titik dianggap pemisah ribuan HANYA bila polanya ribuan (kelompok 3 digit)."""
    t = s(v).replace("Rp", "").replace(" ", "")
    if "," in t and "." in t:                 # 1.234,56
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                             # 0,24  atau  1,234 (ambigu → desimal)
        t = t.replace(",", ".")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.split(".")[1]) == 3
                               and t.split(".")[0].lstrip("-").isdigit()
                               and len(t.split(".")[0].lstrip("-")) <= 3
                               and t.split(".")[0].lstrip("-") != "0"):
        t = t.replace(".", "")                 # 95.000 / 1.234.567
    return t


def num(v, default=0.0) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):            # nilai numerik Excel — jangan disentuh
        return float(v) if math.isfinite(v) else default
    t = _num_text(v)
    if not t:
        return default
    try:
        value = float(t)
        return value if math.isfinite(value) else default
    except ValueError:
        return default


def is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    t = _num_text(v)
    if not t:
        return False
    try:
        return math.isfinite(float(t))
    except ValueError:
        return False


def yes(v, default=True) -> bool:
    t = s(v).lower()
    if not t:
        return default
    return t in ("ya", "y", "yes", "true", "1", "aktif", "active")


def read_sheet(wb, name: str) -> list[dict]:
    """Baris data sheet sebagai dict {kolom: nilai} + nomor baris asli Excel."""
    real = resolve_sheet(wb, name)
    if not real:
        return []
    ws = wb[real]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        warn(name, 0, "sheet kosong")
        return []
    header = [s(h).lower().lstrip("#").strip().rstrip("*") for h in rows[0]]
    alias = {'02_KARYAWAN': {'nik': 'kode_karyawan'},
             '16_LIVEHOST': {'nik_karyawan': 'kode_karyawan'}}.get(name, {})
    for j, h in enumerate(header):
        if h in alias:
            warn(name, 1, f"kolom lama '{h}' diterima sebagai '{alias[h]}' (kode internal, bukan NIK KTP)")
            header[j] = alias[h]
    known = {k for k, *_ in SHEETS[name]["kolom"]}
    if name == '14_KATALOG_JUAL':
        known |= {'kode_akun_kedua', 'tautan_produk_kedua', 'nama'}
    seen_hdr: set[str] = set()
    for j, h in enumerate(header):
        if not h:
            if any(s(r[j]) for r in rows[1:] if r and j < len(r)):
                warn(name, 1, f"kolom {j + 1} tanpa nama kolom tetapi berisi data — diabaikan")
            continue
        if h in seen_hdr:
            err(name, 1, f"nama kolom '{h}' muncul dua kali — kolom kedua akan menimpa yang "
                         "pertama; hapus salah satunya")
        seen_hdr.add(h)
        if h not in known:
            warn(name, 1, f"kolom '{h}' tidak dikenal template — diabaikan")
    missing_hdr = [k for k, req, *_ in SHEETS[name]["kolom"] if req and k not in seen_hdr]
    if missing_hdr:
        err(name, 1, f"kolom wajib tidak ada di baris judul: {', '.join(missing_hdr)}")
    out = []
    for i, raw in enumerate(rows[1:], start=2):
        if raw is None or all(s(c) == "" for c in raw):
            continue
        first = s(raw[0])
        if first == "#" or (first.startswith("#") and first[1:2].isspace()):   # baris contoh
            continue
        rec = {header[j]: raw[j] for j in range(min(len(header), len(raw))) if header[j]}
        rec["__row"] = i
        if name == '14_KATALOG_JUAL' and (s(rec.get('kode_akun_kedua')) or s(rec.get('tautan_produk_kedua'))):
            err(name, i, 'Data akun/tautan kedua belum dipecah; jalankan autofix atau pindahkan ke baris sendiri')
            continue
        if name in ('02_KARYAWAN', '16_LIVEHOST'):
            value = s(rec.get('kode_karyawan'))
            if value.endswith('.0'):
                value = value[:-2]
            if re.fullmatch(r'\d{16}', value):
                err(name, i, 'kode_karyawan berisi 16 digit (indikasi NIK KTP); gunakan kode internal dari 02_KARYAWAN, bukan identitas kependudukan')
                continue
            rec['kode_karyawan'] = value
        bad = [k for k in REF_COLS if s(rec.get(k)).startswith("#")]
        if bad:
            err(name, i, f"{', '.join(bad)} diawali '#': tanda # hanya penanda BARIS CONTOH, "
                         "bukan bagian kode — hapus tanda # (mis. '#HTM' → 'HTM')")
            continue
        out.append(rec)
    if not out:
        warn(name, 0, "tidak ada baris data (hanya judul/contoh)")
    return out


def check_required(sheet: str, recs: list[dict]) -> list[dict]:
    req = [k for k, r, *_ in SHEETS[sheet]["kolom"] if r]
    good = []
    for rec in recs:
        miss = [k for k in req if s(rec.get(k)) == ""]
        if miss:
            err(sheet, rec["__row"], f"kolom wajib kosong: {', '.join(miss)}")
            continue
        good.append(rec)
    return good


def check_enum(sheet: str, rec: dict, col: str, allowed: tuple, default: str = "") -> str:
    v = s(rec.get(col)).lower()
    if not v:
        return default
    if v not in allowed:
        err(sheet, rec["__row"], f"'{col}' = '{v}' tidak sah — pilih: {' | '.join(allowed)}")
        return default
    return v


def dupes(sheet: str, recs: list[dict], key: str) -> None:
    seen: dict[str, int] = {}
    for rec in recs:
        k = s(rec.get(key)).upper()
        if k in seen:
            err(sheet, rec["__row"], f"{key} '{k}' kembar dengan baris {seen[k]} "
                                     "di berkas yang sama")
        else:
            seen[k] = rec["__row"]


async def upsert(db, coll: str, find: dict, doc: dict, apply: bool, sheet: str) -> str:
    """Upsert idempoten + hitung statistik. Mengembalikan id dokumen."""
    st = STATS.setdefault(sheet, {"baru": 0, "diperbarui": 0})
    old = await db[coll].find_one(find, {"_id": 0, "id": 1})
    if old:
        st["diperbarui"] += 1
        if apply:
            await db[coll].update_one({"id": old["id"]},
                                      {"$set": {**doc, "updated_at": now(),
                                                "import_batch": BATCH}})
        return old["id"]
    st["baru"] += 1
    new_id = str(uuid.uuid4())
    if apply:
        await db[coll].insert_one({**doc, "id": new_id, "created_at": now(),
                                   "updated_at": now(), "import_batch": BATCH,
                                   "import_source": doc.get("import_source") or "master_template_v1"})
    return new_id


# ═══════════════════════════════════════════════════════════════════════════════
async def run(path: Path, apply: bool, only: set[str], _validated=False) -> int:  # noqa: C901
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    from motor.motor_asyncio import AsyncIOMotorClient
    from openpyxl import load_workbook

    if apply and not _validated:
        ERRORS.clear(); WARNINGS.clear(); STATS.clear()
        await run(path, False, only)
        if ERRORS:
            return 1
        WARNINGS.clear(); STATS.clear()
    print(f"{B}Berkas   :{X} {path}")
    print(f"{B}Mode     :{X} " + (f"{R}SIMPAN (--apply){X}" if apply
                                  else f"{G}PERIKSA saja (dry-run){X}"))
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    wb = None
    try:
        db = client[os.environ["DB_NAME"]]
        if not apply:
            from master_review_safety import ReadOnlyDatabase
            db = ReadOnlyDatabase(db)
        wb = load_workbook(path, data_only=True)
        return await _import_workbook(wb, db, apply, only)
    finally:
        if wb is not None:
            wb.close()
        client.close()


async def _import_workbook(wb, db, apply, only):
    missing = [n for n in URUTAN if not resolve_sheet(wb, n)]
    WARNINGS.clear()   # resolve_sheet di atas hanya untuk pengecekan awal
    if missing:
        print(f"{Y}Sheet tidak ada (dilewati): {', '.join(missing)}{X}")

    def want(name: str) -> bool:
        return not only or name in only

    # ── peta kode → id (gabungan yang sudah ada di basis data + yang baru dibuat) ──
    async def code_map(coll: str, field: str = "code", extra: dict | None = None) -> dict:
        q = extra or {}
        docs = await db[coll].find(q, {"_id": 0, "id": 1, field: 1}).to_list(20000)
        return {s(d.get(field)).upper(): d["id"] for d in docs if s(d.get(field))}

    loc = await code_map("rahaza_locations")
    col = await code_map("rahaza_colors")
    siz = await code_map("rahaza_sizes")
    mdl = await code_map("rahaza_models")
    mat = await code_map("rahaza_materials")
    emp = await code_map("rahaza_employees", "employee_code")
    acc = await code_map("marketing_platform_accounts", "account_code")
    # Catatan bahan/SKU yang LAHIR DI BERKAS INI. Tanpa ini, pemeriksaan (dry-run)
    # pada basis data kosong selalu melaporkan "material tidak ada" untuk BOM yang
    # materialnya ada di sheet 06/07 berkas yang sama — dry-run jadi tidak pernah bisa
    # bersih, dan pemakai belajar mengabaikan laporannya.
    pending: dict[str, dict] = {}
    pending_colors: dict[str, dict] = {}

    # ── 01 LOKASI ─────────────────────────────────────────────────────────────
    if want("01_LOKASI"):
        from core.location_resolver import normalize_role, ALL_LOCATION_ROLES
        recs = check_required("01_LOKASI", read_sheet(wb, "01_LOKASI"))
        dupes("01_LOKASI", recs, "kode")
        role_owner: dict[str, int] = {}
        for r in recs:
            tipe = check_enum("01_LOKASI", r, "tipe",
                              ("gudang", "kantor", "produksi", "toko"), "gudang")
            code = s(r["kode"]).upper()
            induk = s(r.get("kode_induk")).upper()
            if induk and induk not in loc:
                err("01_LOKASI", r["__row"], f"kode_induk '{induk}' tidak ada di sheet ini "
                                             "(baris sebelumnya) maupun di sistem")
                continue
            role = normalize_role(r.get("peran"))
            if role and role not in ALL_LOCATION_ROLES:
                err("01_LOKASI", r["__row"], f"peran '{s(r.get('peran'))}' tidak dikenal — pilih: "
                                             f"{' | '.join(ALL_LOCATION_ROLES)} (kain = bahan)")
                continue
            if role and role in role_owner:
                err("01_LOKASI", r["__row"], f"peran '{role}' sudah dipegang baris {role_owner[role]} — "
                                             "satu peran stok hanya boleh untuk SATU lokasi")
                continue
            if role:
                role_owner[role] = r["__row"]
                other = await db.rahaza_locations.find_one(
                    {"storage_role": role, "code": {"$ne": code}, "active": {"$ne": False}},
                    {"_id": 0, "code": 1})
                if other:
                    err("01_LOKASI", r["__row"], f"peran '{role}' sudah dipegang lokasi '{other.get('code')}' "
                                                 "di sistem — lepaskan dulu dari layar Master Lokasi")
                    continue
            loc[code] = await upsert(db, "rahaza_locations", {"code": code}, {
                "code": code, "name": s(r["nama"]), "type": tipe,
                "parent_id": loc.get(induk),
                "active": yes(r.get("aktif")), "storage_role": role,
            }, apply, "01_LOKASI")
        if recs:
            for role in ("fg", "bahan", "aksesoris", "karantina"):
                if role in role_owner:
                    continue
                if not await db.rahaza_locations.find_one(
                        {"$or": [{"storage_role": role}, {"code": {"$in": [
                            {"fg": "ZNA-FG", "bahan": "ZNA-KAIN", "aksesoris": "ZNA-AKSESORIS",
                             "karantina": "ZNA-KARANTINA"}[role]]}}]}, {"_id": 0, "id": 1}):
                    warn("01_LOKASI", 0, f"tidak ada lokasi berperan '{role}' di berkas maupun sistem — "
                                         "stok FG/kain/aksesoris/karantina tidak punya tujuan sampai peran diisi")

    # ── 02 KARYAWAN (+ profil payroll) ────────────────────────────────────────
    if want("02_KARYAWAN"):
        recs = check_required("02_KARYAWAN", read_sheet(wb, "02_KARYAWAN"))
        dupes("02_KARYAWAN", recs, "kode_karyawan")
        for r in recs:
            skema = check_enum("02_KARYAWAN", r, "skema_upah",
                               ("bulanan", "borongan", "harian"), "bulanan")
            lk = s(r.get("kode_lokasi")).upper()
            if lk and lk not in loc:
                err("02_KARYAWAN", r["__row"], f"kode_lokasi '{lk}' tidak ada di 01_LOKASI "
                                               "maupun di sistem")
            nik = s(r["kode_karyawan"]).upper()
            eid = await upsert(db, "rahaza_employees", {"employee_code": nik}, {
                "employee_code": nik, "name": s(r["nama"]),
                "role_hint": s(r.get("jabatan")).lower(), "phone": phone(r.get("telepon")),
                "join_date": s(r.get("tanggal_masuk"))[:10] or None,
                "location_id": loc.get(lk), "active": yes(r.get("aktif")),
            }, apply, "02_KARYAWAN")
            emp[nik] = eid
            scheme = {"bulanan": "monthly", "borongan": "piece_rate", "harian": "daily"}[skema]
            await upsert(db, "rahaza_payroll_profiles", {"employee_id": eid}, {
                "employee_id": eid, "pay_scheme": scheme,
                "period_type": "monthly", "base_rate": num(r.get("gaji_pokok")),
                "overtime_rate": num(r.get("tarif_lembur_per_jam")),
                "pcs_process_rates": [], "active": True,
                "notes": f"Impor master {BATCH}",
            }, apply, "02_KARYAWAN·profil_gaji")

    # ── 03 WARNA / 04 UKURAN / 05 PROSES ──────────────────────────────────────
    if want("03_WARNA"):
        recs = check_required("03_WARNA", read_sheet(wb, "03_WARNA"))
        dupes("03_WARNA", recs, "kode")
        for r in recs:
            code = s(r["kode"]).upper()
            col[code] = await upsert(db, "rahaza_colors", {"code": code}, {
                "code": code, "name": s(r["nama"]), "hex": s(r.get("hex")),
                "order_seq": int(num(r.get("urutan"))), "active": True,
            }, apply, "03_WARNA")
            pending_colors[code] = {'name': s(r['nama'])}

    if want("04_UKURAN"):
        recs = check_required("04_UKURAN", read_sheet(wb, "04_UKURAN"))
        dupes("04_UKURAN", recs, "kode")
        for r in recs:
            code = s(r["kode"]).upper()
            if not code.replace("-", "").replace(".", "").isalnum():
                err("04_UKURAN", r["__row"], f"kode ukuran '{code}' memuat karakter yang "
                                             "tidak boleh masuk SKU (spasi/garis miring) — "
                                             "pakai mis. ALLSIZE, 2XL, 28-30")
                continue
            siz[code] = await upsert(db, "rahaza_sizes", {"code": code}, {
                "code": code, "name": s(r["nama"]),
                "order_seq": int(num(r.get("urutan"))), "active": True,
            }, apply, "04_UKURAN")

    if want("05_PROSES"):
        recs = check_required("05_PROSES", read_sheet(wb, "05_PROSES"))
        dupes("05_PROSES", recs, "kode")
        for r in recs:
            code = s(r["kode"]).upper()
            await upsert(db, "rahaza_processes", {"code": code}, {
                "code": code, "name": s(r["nama"]),
                "order_seq": int(num(r.get("urutan"))),
                "is_rework": yes(r.get("permak"), False),
                "description": s(r.get("keterangan")), "active": True,
            }, apply, "05_PROSES")

    # ── 06 KAIN & BENANG / 07 AKSESORIS ───────────────────────────────────────
    UNITS = ("pcs", "kg", "gram", "m", "yard", "roll", "pack", "gross", "lusin")
    if want("06_MATERIAL_KAIN"):
        recs = check_required("06_MATERIAL_KAIN", read_sheet(wb, "06_MATERIAL_KAIN"))
        dupes("06_MATERIAL_KAIN", recs, "kode")
        JENIS_ALIAS = {"kain": "fabric", "knit": "fabric", "woven": "fabric", "rajut": "fabric",
                       "benang": "yarn"}
        for r in recs:
            jv = s(r.get("jenis")).lower()
            if jv in JENIS_ALIAS:
                r["jenis"] = JENIS_ALIAS[jv]
            jenis = check_enum("06_MATERIAL_KAIN", r, "jenis", ("fabric", "yarn"), "")
            unit = check_enum("06_MATERIAL_KAIN", r, "satuan_dasar", UNITS, "")
            if not is_num(r.get("harga_per_satuan")) or num(r.get("harga_per_satuan")) <= 0:
                warn("06_MATERIAL_KAIN", r["__row"], "harga_per_satuan kosong/0 — HPP awal bahan "
                                                     "ini akan 0 sampai ada pembelian")
            if not jenis or not unit:
                continue
            code = s(r["kode"]).upper()
            mat[code] = await upsert(db, "rahaza_materials", {"code": code}, {
                "code": code, "name": s(r["nama"]), "type": jenis, "unit": unit,
                "base_uom": unit, "purchase_uom": unit, "issue_uom": unit, "display_uom": unit,
                "uoms": [{"code": unit, "name": unit.upper(), "factor": 1.0,
                          "is_base": True, "level": 0}],
                "composition": s(r.get("komposisi")), "color": s(r.get("warna")),
                "gsm": num(r.get("gramasi_gsm")) or None,
                "width_cm": num(r.get("lebar_cm")) or None,
                "unit_cost": num(r.get("harga_per_satuan")),
                "min_stock": num(r.get("stok_minimum")),
                "cost_method": "moving_average", "active": True,
            }, apply, "06_MATERIAL_KAIN")
            pending[code] = {"id": mat[code], "code": code, "name": s(r["nama"]),
                             "type": jenis, "unit": unit, "base_uom": unit, "category_name": "",
                             "gsm": num(r.get("gramasi_gsm")) or None,
                             "width_cm": num(r.get("lebar_cm")) or None,
                             "unit_cost": num(r.get("harga_per_satuan")),
                             "composition": s(r.get("komposisi")), "color": s(r.get("warna"))}

    if want("07_AKSESORIS"):
        recs = check_required("07_AKSESORIS", read_sheet(wb, "07_AKSESORIS"))
        dupes("07_AKSESORIS", recs, "kode")
        for r in recs:
            unit = check_enum("07_AKSESORIS", r, "satuan_dasar", UNITS, "")
            if not unit:
                continue
            if s(r.get("isi_per_kemasan")) and not is_num(r.get("isi_per_kemasan")):
                err("07_AKSESORIS", r["__row"], f"isi_per_kemasan '{s(r.get('isi_per_kemasan'))}' "
                                                "harus ANGKA saja (mis. 144), tanpa satuan/teks")
                continue
            if not is_num(r.get("harga_per_satuan")) or num(r.get("harga_per_satuan")) <= 0:
                warn("07_AKSESORIS", r["__row"], "harga_per_satuan kosong/0 — HPP awal aksesoris "
                                                 "ini akan 0 sampai ada pembelian")
            pack_size = num(r.get("isi_per_kemasan"), 1.0) or 1.0
            code = s(r["kode"]).upper()
            mat[code] = await upsert(db, "rahaza_materials", {"code": code}, {
                "code": code, "name": s(r["nama"]), "type": "accessory", "unit": unit,
                "base_uom": unit, "purchase_uom": unit, "issue_uom": unit, "display_uom": unit,
                "uoms": [{"code": unit, "name": unit.upper(), "factor": 1.0,
                          "is_base": True, "level": 0}],
                "category_name": s(r.get("kategori")),
                "unit_cost": num(r.get("harga_per_satuan")),
                "min_stock": num(r.get("stok_minimum")),
                "pack_unit": s(r.get("satuan_kemasan")) or "pack", "pack_size": pack_size,
                "cost_method": "moving_average", "active": True,
            }, apply, "07_AKSESORIS")
            pending[code] = {"id": mat[code], "code": code, "name": s(r["nama"]),
                             "type": "accessory", "unit": unit, "base_uom": unit,
                             "pack_unit": s(r.get("satuan_kemasan")) or "pack", "pack_size": pack_size,
                             "unit_cost": num(r.get("harga_per_satuan")),
                             "category_name": s(r.get("kategori"))}

    # ── 08 MODEL ──────────────────────────────────────────────────────────────
    if want("08_MODEL"):
        recs = check_required("08_MODEL", read_sheet(wb, "08_MODEL"))
        dupes("08_MODEL", recs, "kode")
        # 2026-09-12 (owner): kolom `kategori` DITAUTKAN ke master kategori (category_id),
        # bukan sekadar teks — kategori yang belum ada dibuat (Top, One set, Inner, Tunik…).
        cats = {s(d.get("name")).lower(): d for d in await db.rahaza_product_categories.find(
            {"active": True}, {"_id": 0, "id": 1, "name": 1, "sku_prefix": 1, "code": 1}).to_list(500)}
        used_prefix = {s(d.get("sku_prefix")).upper() for d in cats.values()}
        for r in recs:
            code = s(r["kode"]).upper()
            cat_name = s(r.get("kategori"))
            cat = cats.get(cat_name.lower()) if cat_name else None
            if cat_name and not cat:
                base = "".join(ch for ch in cat_name.upper() if ch.isalnum())[:3] or "KAT"
                prefix, n = base, 2
                while prefix in used_prefix:
                    prefix, n = f"{base[:2]}{n}", n + 1
                used_prefix.add(prefix)
                cid = await upsert(db, "rahaza_product_categories", {"code": cat_name.upper().replace(" ", "_")}, {
                    "code": cat_name.upper().replace(" ", "_"), "name": cat_name, "sku_prefix": prefix,
                    "order_seq": 100 + len(cats), "description": "", "active": True,
                    "created_from": "master_import",
                }, apply, "08_MODEL·kategori")
                cat = {"id": cid, "name": cat_name, "sku_prefix": prefix}
                cats[cat_name.lower()] = cat
            mdl[code] = await upsert(db, "rahaza_models", {"code": code}, {
                "code": code, "name": s(r["nama"]),
                "category": cat_name,
                "category_id": (cat or {}).get("id"),
                "category_name": (cat or {}).get("name") or cat_name,
                "description": s(r.get("keterangan")),
                "retail_price": num(r.get("harga_jual_dasar")), "active": True,
            }, apply, "08_MODEL")

    # ── 09 BARANG JADI (SKU) ──────────────────────────────────────────────────
    if want("09_BARANG_JADI"):
        recs = check_required("09_BARANG_JADI", read_sheet(wb, "09_BARANG_JADI"))
        dupes("09_BARANG_JADI", recs, "sku")
        colnames = {v: k for k, v in [(c, i) for i, c in enumerate([])]}  # noqa: F841
        cmap = {s(d.get("code")).upper(): d for d in await db.rahaza_colors.find(
            {}, {"_id": 0, "id": 1, "code": 1, "name": 1, "hex": 1}).to_list(5000)}
        smap = {s(d.get("code")).upper(): d for d in await db.rahaza_sizes.find(
            {}, {"_id": 0, "id": 1, "code": 1}).to_list(5000)}
        for r in recs:
            mk, ck, sk = (s(r["kode_model"]).upper(), s(r["kode_warna"]).upper(),
                          s(r["kode_ukuran"]).upper())
            bad = [f"{lbl} '{v}'" for lbl, v, ok in
                   (("kode_model", mk, mk in mdl), ("kode_warna", ck, ck in col),
                    ("kode_ukuran", sk, sk in siz)) if not ok]
            if bad:
                err("09_BARANG_JADI", r["__row"],
                    f"{', '.join(bad)} belum ada — isi sheet masternya lebih dulu")
                continue
            sku = s(r["sku"]).upper()
            c_doc, s_doc = cmap.get(ck, {}), smap.get(sk, {})
            mat[sku] = await upsert(db, "rahaza_materials", {"code": sku}, {
                "code": sku, "sku": sku, "name": s(r["nama"]), "type": "fg",
                "unit": s(r.get("satuan")) or "pcs",
                "model_id": mdl[mk], "model_code": mk,
                "size_id": siz[sk], "size_code": sk,
                "color_id": col[ck], "color_code": ck,
                "color": c_doc.get("name") or ck, "color_name": c_doc.get("name") or ck,
                "color_hex": c_doc.get("hex") or "",
                "weight_gram": num(r.get("berat_gram")),
                "retail_price_master": num(r.get("harga_jual")),
                "min_stock_qty": num(r.get("stok_minimum")), "active": True,
            }, apply, "09_BARANG_JADI")
            pending[sku] = {"id": mat[sku], "code": sku, "name": s(r["nama"]), "type": "fg",
                            "unit": s(r.get("satuan")) or "pcs",
                            "color": c_doc.get("name") or ck, "model_id": mdl[mk]}

    # ── 10 BOM (kain + benang + AKSESORIS) ────────────────────────────────────
    if want("10_BOM"):
        from master_import_bom import import_boms
        await import_boms(wb, db, pending, mdl, siz, col, apply, sys.modules[__name__], pending_colors)

    # ── 11 VENDOR CMT / 12 KLIEN MAKLON ───────────────────────────────────────
    if want("11_VENDOR_CMT"):
        recs = check_required("11_VENDOR_CMT", read_sheet(wb, "11_VENDOR_CMT"))
        dupes("11_VENDOR_CMT", recs, "kode")
        for r in recs:
            code = s(r["kode"]).upper()
            await upsert(db, "vendor_partners", {"code": code}, {
                "code": code, "name": s(r["nama"]),
                "contact_name": s(r.get("nama_kontak")), "contact_phone": phone(r.get("telepon")),
                "address": s(r.get("alamat")), "capacity_pcs": num(r.get("kapasitas_pcs")),
                "notes": s(r.get("keterangan")), "active": True, "is_active": True,
            }, apply, "11_VENDOR_CMT")

    if want("12_KLIEN_MAKLON"):
        recs = check_required("12_KLIEN_MAKLON", read_sheet(wb, "12_KLIEN_MAKLON"))
        dupes("12_KLIEN_MAKLON", recs, "kode")
        for r in recs:
            code = s(r["kode"]).upper()
            await upsert(db, "dewi_maklon_clients", {"code": code}, {
                "code": code, "name": s(r["nama"]),
                "contact_name": s(r.get("nama_kontak")), "contact_phone": phone(r.get("telepon")),
                "address": s(r.get("alamat")), "notes": s(r.get("keterangan")),
                "active": True,
            }, apply, "12_KLIEN_MAKLON")

    # ── 13 AKUN TOKO ──────────────────────────────────────────────────────────
    PLAT = ("shopee", "tiktok", "tokopedia", "lazada", "instagram", "facebook")
    if want("13_AKUN_TOKO"):
        recs = check_required("13_AKUN_TOKO", read_sheet(wb, "13_AKUN_TOKO"))
        dupes("13_AKUN_TOKO", recs, "kode_akun")
        for r in recs:
            plat = check_enum("13_AKUN_TOKO", r, "platform", PLAT, "")
            if not plat:
                continue
            code = s(r["kode_akun"]).upper()
            acc[code] = await upsert(db, "marketing_platform_accounts",
                                     {"account_code": code}, {
                                         "account_code": code, "account_name": s(r["nama_akun"]),
                                         "platform": plat, "username": s(r.get("username")),
                                         "group": s(r.get("grup")),
                                         "status": s(r.get("status")).lower() or "active",
                                     }, apply, "13_AKUN_TOKO")

    # ── 14 KATALOG JUAL ───────────────────────────────────────────────────────
    if want("14_KATALOG_JUAL"):
        recs = check_required("14_KATALOG_JUAL", read_sheet(wb, "14_KATALOG_JUAL"))
        seen_catalog = {}
        for r in recs:
            key = (s(r['kode_akun']).upper(), s(r['sku']).upper())
            values = tuple(s(r.get(k)) for k in ('harga_jual', 'harga_coret', 'tautan_produk', 'aktif'))
            if key in seen_catalog:
                previous, previous_values = seen_catalog[key]
                if values != previous_values:
                    err('14_KATALOG_JUAL', r['__row'], f'Pasangan toko–SKU {key} konflik dengan baris {previous}; pilih harga/tautan yang benar')
                else:
                    warn('14_KATALOG_JUAL', r['__row'], f'Pasangan toko–SKU {key} identik dengan baris {previous}; hanya satu item tersimpan')
            else:
                seen_catalog[key] = (r['__row'], values)
        fg = {s(d.get("code")).upper(): d for d in await db.rahaza_materials.find(
            {"type": "fg"}, {"_id": 0, "id": 1, "code": 1, "name": 1, "color": 1,
                             "model_id": 1}).to_list(50000)}
        fg.update({k: v for k, v in pending.items() if v.get("type") == "fg"})
        adocs = {d["id"]: d for d in await db.marketing_platform_accounts.find(
            {}, {"_id": 0, "id": 1, "platform": 1, "account_name": 1}).to_list(500)}
        for r in recs:
            ak, sku = s(r["kode_akun"]).upper(), s(r["sku"]).upper()
            if ak not in acc:
                err("14_KATALOG_JUAL", r["__row"], f"kode_akun '{ak}' belum ada di 13_AKUN_TOKO")
                continue
            if sku not in fg:
                err("14_KATALOG_JUAL", r["__row"], f"sku '{sku}' bukan barang jadi yang "
                                                   "terdaftar — isi 09_BARANG_JADI lebih dulu")
                continue
            harga = num(r["harga_jual"])
            if harga <= 0:
                err("14_KATALOG_JUAL", r["__row"], "harga_jual harus lebih besar dari 0 — "
                                                   "margin tidak bisa dihitung dari harga 0")
                continue
            coret = num(r.get("harga_coret"))
            if 0 < coret < harga:
                err("14_KATALOG_JUAL", r["__row"], f"harga_coret ({coret:,.0f}) lebih kecil dari "
                                                   f"harga_jual ({harga:,.0f}) — kemungkinan "
                                                   "tertukar: harga_coret = harga SEBELUM diskon")
                continue
            f, a = fg[sku], adocs.get(acc[ak], {})
            await upsert(db, "marketing_catalog_items",
                         {"account_id": acc[ak], "sku": sku}, {
                             "account_id": acc[ak], "platform": a.get("platform") or "",
                             "sku": sku, "name": f.get("name") or sku,
                             "fg_material_id": f["id"], "material_id": f["id"],
                             "fg_code": sku, "fg_name": f.get("name") or sku,
                             "fg_color": f.get("color") or "", "model_id": f.get("model_id"),
                             "unit": "pcs", "source": "master_import",
                             "platform_price": harga, "harga_jual": harga, "price": harga,
                             "harga_coret": num(r.get("harga_coret")),
                             "original_price": num(r.get("harga_coret")),
                             "platform_url": s(r.get("tautan_produk")),
                             "is_active": yes(r.get("aktif")),
                         }, apply, "14_KATALOG_JUAL")

    # ── 15 KOL / KREATOR ──────────────────────────────────────────────────────
    if want("15_KOL_KREATOR"):
        recs = check_required("15_KOL_KREATOR", read_sheet(wb, "15_KOL_KREATOR"))
        dupes("15_KOL_KREATOR", recs, "kode_kreator")
        for r in recs:
            tipe = check_enum("15_KOL_KREATOR", r, "tipe", ("new", "kontrak", "continue"), "")
            mode = check_enum("15_KOL_KREATOR", r, "insentif_mode",
                              ("none", "per_pcs", "target_bonus", "both"), "none")
            if not tipe:
                continue
            if tipe == "new" and mode != "none":
                err("15_KOL_KREATOR", r["__row"], "kreator tipe 'new' tidak berhak insentif — "
                                                  "ubah tipe ke kontrak/continue atau "
                                                  "insentif_mode ke none")
                continue
            ak_codes = [x.strip().upper() for x in s(r.get("kode_akun_toko")).split(",") if x.strip()]
            unknown = [x for x in ak_codes if x not in acc]
            if unknown:
                err("15_KOL_KREATOR", r["__row"], f"kode_akun_toko {unknown} belum ada di "
                                                  "13_AKUN_TOKO")
                continue
            code = s(r["kode_kreator"]).upper()
            await upsert(db, "marketing_kol_creators", {"creator_code": code}, {
                "creator_code": code, "name": s(r["nama"]), "creator_type": tipe,
                "domicile": s(r.get("domisili")), "phone": phone(r.get("telepon")),
                "login_email": s(r.get("email_portal")).lower(),
                "assigned_account_ids": [acc[x] for x in ak_codes],
                "status": "active",
                "incentive": {"mode": mode, "rate_per_pcs": num(r.get("insentif_per_pcs")),
                              "target_pcs": int(num(r.get("target_pcs"))),
                              "bonus_amount": num(r.get("bonus_target")),
                              "period_months": int(num(r.get("periode_bulan"), 3)) or 3,
                              "period_start": "", "notes": f"Impor master {BATCH}"},
            }, apply, "15_KOL_KREATOR")

    # ── 16 LIVEHOST ───────────────────────────────────────────────────────────
    if want("16_LIVEHOST"):
        recs = check_required("16_LIVEHOST", read_sheet(wb, "16_LIVEHOST"))
        dupes("16_LIVEHOST", recs, "email")
        for r in recs:
            nik = s(r["kode_karyawan"]).upper()
            if nik not in emp:
                err("16_LIVEHOST", r["__row"], f"kode_karyawan '{nik}' belum ada di "
                                               "02_KARYAWAN — gaji host dibaca dari payroll HR, "
                                               "jadi tautan ini wajib")
                continue
            ak_codes = [x.strip().upper() for x in s(r.get("kode_akun_toko")).split(",") if x.strip()]
            unknown = [x for x in ak_codes if x not in acc]
            if unknown:
                err("16_LIVEHOST", r["__row"], f"kode_akun_toko {unknown} belum ada di "
                                               "13_AKUN_TOKO")
                continue
            email = s(r["email"]).lower()
            await upsert(db, "marketing_livehosts", {"email": email}, {
                "email": email, "name": s(r["nama"]), "phone": phone(r.get("telepon")),
                "employee_id": emp[nik], "employee_code": nik,
                "employment_type": "employee", "pay_mode": "monthly_hr",
                "hourly_rate": 0.0,
                "assigned_account_ids": [acc[x] for x in ak_codes],
                "status": s(r.get("status")).lower() or "active",
            }, apply, "16_LIVEHOST")

    # ── 17 USER (akun login) / 18 TUNJANGAN ───────────────────────────────────
    if want("17_USER"):
        await import_users(wb, db, emp, apply)
    if want("18_TUNJANGAN"):
        await import_allowances(wb, db, emp, apply)

    # ── LAPORAN ───────────────────────────────────────────────────────────────
    return 0


async def import_users(wb, db, emp: dict, apply: bool) -> None:
    """17_USER → `users`. Tanpa sandi di Excel; user lama tidak pernah kehilangan sandinya."""
    from auth import hash_password
    recs = check_required("17_USER", read_sheet(wb, "17_USER"))
    dupes("17_USER", recs, "email")
    roles = {s(d.get("name")) for d in await db.roles.find({}, {"_id": 0, "name": 1}).to_list(500)}
    initial_hash = None
    for r in recs:
        email = s(r["email"]).lower()
        if "@" not in email or " " in email:
            err("17_USER", r["__row"], f"email '{email}' tidak sah")
            continue
        nik = s(r["nik_karyawan"]).upper()
        if nik not in emp:
            err("17_USER", r["__row"], f"nik_karyawan '{nik}' tidak ada di 02_KARYAWAN maupun sistem — "
                                       "akun tanpa tautan karyawan tidak disimpan")
            continue
        role = s(r["peran"]).lower()
        if role in PROTECTED_USER_ROLES or role not in roles:
            err("17_USER", r["__row"], f"peran '{role}' tidak terdaftar di daftar peran sistem (koleksi roles)")
            continue
        status = check_enum("17_USER", r, "status", ("active", "inactive"), "active")
        old = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "role": 1})
        if old and old.get("role") in PROTECTED_USER_ROLES:
            err("17_USER", r["__row"], f"'{email}' adalah akun {old['role']} — tidak boleh diubah lewat impor")
            continue
        st = STATS.setdefault("17_USER", {"baru": 0, "diperbarui": 0})
        doc = {"email": email, "name": s(r["nama"]), "role": role, "status": status,
               "employee_id": emp[nik], "employee_code": nik, "is_active": status == "active"}
        if old:
            st["diperbarui"] += 1
            if apply:   # sandi & must_change_password TIDAK disentuh
                await db.users.update_one({"id": old["id"]}, {"$set": {
                    **doc, "updated_at": now(), "import_batch": BATCH}})
            continue
        st["baru"] += 1
        if apply:
            if initial_hash is None:
                initial_hash = hash_password(os.environ.get(INITIAL_PASSWORD_ENV) or INITIAL_PASSWORD_DEFAULT)
            await db.users.insert_one({**doc, "id": str(uuid.uuid4()), "password": initial_hash,
                                       "must_change_password": True, "created_at": now(),
                                       "updated_at": now(), "import_batch": BATCH,
                                       "import_source": "master_template_v1"})
    if recs and STATS.get("17_USER", {}).get("baru"):
        warn("17_USER", 0, f"{STATS['17_USER']['baru']} akun baru memakai sandi awal bersama "
                           f"(env {INITIAL_PASSWORD_ENV}) dan WAJIB menggantinya saat login pertama")


async def import_allowances(wb, db, emp: dict, apply: bool) -> None:
    """18_TUNJANGAN → `da_payroll_allowances` (kunci `code`; employee_ids = uuid karyawan)."""
    from routes.rahaza_payroll_shared import VALID_ALLOWANCE_CALC_TYPES
    SCOPE = {"semua": "all", "departemen": "department", "karyawan": "employee"}
    recs = check_required("18_TUNJANGAN", read_sheet(wb, "18_TUNJANGAN"))
    dupes("18_TUNJANGAN", recs, "kode")
    for r in recs:
        code = s(r["kode"]).upper()
        calc = check_enum("18_TUNJANGAN", r, "cara_hitung", tuple(VALID_ALLOWANCE_CALC_TYPES), "")
        if not calc:
            continue
        if not is_num(r.get("nominal")) or num(r.get("nominal")) <= 0:
            err("18_TUNJANGAN", r["__row"], "nominal harus angka lebih besar dari 0")
            continue
        scope_in = check_enum("18_TUNJANGAN", r, "berlaku_untuk", tuple(SCOPE), "semua")
        scope = SCOPE[scope_in]
        dept = s(r.get("departemen"))
        codes = [x.strip().upper() for x in s(r.get("nik_karyawan")).split(",") if x.strip()]
        if scope == "department" and not dept:
            err("18_TUNJANGAN", r["__row"], "berlaku_untuk = departemen tetapi kolom departemen kosong")
            continue
        if scope == "employee" and not codes:
            err("18_TUNJANGAN", r["__row"], "berlaku_untuk = karyawan tetapi nik_karyawan kosong")
            continue
        unknown = [c for c in codes if c not in emp]
        if unknown:
            err("18_TUNJANGAN", r["__row"], f"nik_karyawan {unknown} tidak ada di 02_KARYAWAN maupun sistem")
            continue
        if scope != "employee" and codes:
            warn("18_TUNJANGAN", r["__row"], "nik_karyawan diabaikan karena berlaku_untuk bukan 'karyawan'")
        old = await db.da_payroll_allowances.find_one({"code": code}, {"_id": 0, "allowance_id": 1})
        await upsert(db, "da_payroll_allowances", {"code": code}, {
            "code": code, "allowance_id": (old or {}).get("allowance_id") or str(uuid.uuid4()),
            "name": s(r["nama"]), "amount": num(r["nominal"]), "calc_type": calc,
            "is_fixed_wage": yes(r.get("upah_tetap"), False), "applicable_to": scope,
            "department": dept if scope == "department" else "",
            "employee_ids": [emp[c] for c in codes] if scope == "employee" else [],
            "description": s(r.get("keterangan")), "is_active": True,
        }, apply, "18_TUNJANGAN")


def write_report_xlsx(dest: Path) -> None:
    """Laporan kesalahan/peringatan per baris dalam Excel — untuk dikirim balik ke pengisi."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from master_autofix_rules import redact
    wb = Workbook()
    ws = wb.active
    ws.title = "RINGKASAN"
    ws.append(["Sheet", "Pesan kesalahan (DITOLAK)", "Pesan peringatan", "Rencana baru", "Rencana diperbarui"])
    e_by, w_by = {}, {}
    for sh, row, msg in ERRORS:
        e_by.setdefault(sh, []).append((row, msg))
    for sh, row, msg in WARNINGS:
        w_by.setdefault(sh, []).append((row, msg))
    for name in URUTAN:
        st = STATS.get(name, {})
        ws.append([name, len(e_by.get(name, [])), len(w_by.get(name, [])),
                   st.get("baru", 0), st.get("diperbarui", 0)])
    ws.append([])
    ws.append(["TOTAL", len(ERRORS), len(WARNINGS)])
    d = wb.create_sheet("KESALAHAN")
    d.append(["Sheet", "Baris Excel", "Kesalahan (harus diperbaiki)"])
    for sh, row, msg in ERRORS:
        d.append([sh, row or "", redact(msg)])
    p = wb.create_sheet("PERINGATAN")
    p.append(["Sheet", "Baris Excel", "Peringatan (tidak menghalangi, tapi periksa)"])
    for sh, row, msg in WARNINGS:
        p.append([sh, row or "", redact(msg)])
    for sheet in (ws, d, p):
        for c in sheet[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3A5F")
        sheet.column_dimensions["A"].width = 20
        sheet.column_dimensions["B"].width = 14
        sheet.column_dimensions["C"].width = 110
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    wb.close()
    print(f"{C}Laporan Excel: {dest}{X}")


def print_report(apply: bool) -> int:
    print(f"\n{B}{'─' * 74}{X}")
    print(f"{B}RENCANA PER SHEET{X}")
    if not STATS:
        print("  (tidak ada baris data — hanya baris contoh/komentar?)")
    for name in URUTAN:
        st = STATS.get(name)
        if st:
            print(f"  {name:18s} baru {st['baru']:5d} · diperbarui {st['diperbarui']:5d}")
        sub = STATS.get(f"{name}·profil_gaji")
        if sub:
            print(f"    └ profil gaji     baru {sub['baru']:5d} · diperbarui {sub['diperbarui']:5d}")
        sub = STATS.get(f"{name}·kategori")
        if sub:
            print(f"    └ kategori baru   baru {sub['baru']:5d} · diperbarui {sub['diperbarui']:5d}")
        sub = STATS.get(f"{name}·potongan")
        if sub:
            print(f"    └ master potongan baru {sub['baru']:5d} · dipakai-ulang {sub['diperbarui']:5d}")

    if WARNINGS:
        print(f"\n{Y}{B}{len(WARNINGS)} PERINGATAN{X} (tidak menghalangi penyimpanan)")
        by_w: dict[str, list] = {}
        for sh, row, msg in WARNINGS:
            by_w.setdefault(sh, []).append((row, msg))
        for sh, items in by_w.items():
            print(f"  {Y}{sh}{X} ({len(items)})")
            for row, msg in items[:5]:
                print(f"    baris {row or '-':>4}  {msg}")
            if len(items) > 5:
                print(f"    … {len(items) - 5} peringatan lain sejenis")

    if ERRORS:
        print(f"\n{R}{B}{len(ERRORS)} PESAN KESALAHAN — tidak ada yang disimpan{X}")
        by_sheet: dict[str, list] = {}
        for sh, row, msg in ERRORS:
            by_sheet.setdefault(sh, []).append((row, msg))
        for sh, items in by_sheet.items():
            print(f"\n  {Y}{sh}{X} ({len(items)} baris)")
            for row, msg in items[:25]:
                print(f"    baris {row or '-':>4}  {msg}")
            if len(items) > 25:
                print(f"    … {len(items) - 25} baris lain sejenis")
        print(f"\n{R}Perbaiki di berkas Excel lalu jalankan lagi.{X}")
        return 1

    if apply:
        print(f"\n{G}{B}TERSIMPAN.{X} Penanda batch: {C}{BATCH}{X}")
        print(f"{Y}Belum termasuk (memang di luar master):{X}")
        print("  · Saldo awal stok / piutang / hutang / kas — impor terpisah")
        print("  · Password portal kreator & livehost — dibuat dari layar Marketing")
        print("  · HPP: jalankan hitung ulang HPP dari layar Costing setelah BOM masuk")
    else:
        print(f"\n{G}{B}PEMERIKSAAN BERSIH — tidak ada kesalahan.{X}")
        print(f"Jalankan lagi dengan {C}--apply{X} untuk menyimpan.")
    return 0


async def main(path: Path, apply: bool, only: set[str], report: Path | None = None) -> int:
    """DUA TAHAP. Tahap-1 memeriksa seluruh berkas TANPA menulis; penyimpanan baru
    dijalankan bila tahap-1 bersih. Kalau divalidasi sambil menulis, berkas yang cacat
    di baris ke-500 sudah meninggalkan 499 dokumen setengah jadi — dan itu jauh lebih
    sulit diperbaiki daripada sekadar gagal."""
    ERRORS.clear()
    WARNINGS.clear()
    STATS.clear()
    unknown = only - set(URUTAN)
    if unknown:
        err('BERKAS', 0, f"Sheet --only tidak dikenal: {', '.join(sorted(unknown))}")
        return print_report(False)
    await run(path, False, only)
    if report:
        write_report_xlsx(report)
    if ERRORS:
        return print_report(False)
    if not apply:
        return print_report(False)
    ERRORS.clear()
    WARNINGS.clear()
    STATS.clear()
    await run(path, True, only, _validated=True)
    return print_report(True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--apply", action="store_true", help="simpan (bawaan: periksa saja)")
    ap.add_argument("--only", default="", help="hanya sheet tertentu, pisahkan koma")
    ap.add_argument("--report", default="", help="tulis laporan kesalahan/peringatan ke .xlsx")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    sys.exit(asyncio.run(main(Path(a.file), a.apply, only,
                              Path(a.report) if a.report else None)))
