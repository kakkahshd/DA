#!/usr/bin/env python3
"""scripts/prepare_golive_workbook.py — SALINAN go-live dari berkas master owner.

    python3 scripts/prepare_golive_workbook.py SUMBER.xlsx TUJUAN.xlsx

Berkas asli TIDAK diubah. Yang dilakukan pada salinan — semuanya keputusan owner
(2026-09), bukan tebakan, dan setiap perubahan dicatat di sheet DAFTAR_PERBAIKAN:
  1. 01_LOKASI: kolom `peran` diisi (fg/kain/aksesoris/karantina/cutting) sesuai pemetaan owner.
  2. 14_KATALOG_JUAL: pasangan toko–SKU yang KONFLIK harga (dua baris, harga beda) dikeluarkan
     SELURUHNYA dari sheet katalog dan dipindah ke DAFTAR_PERBAIKAN menunggu jawaban klien.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

# Keputusan owner: peran lokasi (kain = GD-L2 Gudang Lantai 2).
PERAN = {"GD-L1-RAK": "fg", "GD-L1-ACC": "aksesoris", "GD-L1-QC": "karantina",
         "GD-L2-CUT": "cutting", "GD-L2": "kain"}
CAT_KEYS = ("harga_jual", "harga_coret", "tautan_produk", "aktif")
# Keputusan owner 2026-09-12: konflik harga DA-4401-* (85.999 vs 172.999) → 85.999 untuk semua.
CATALOG_PRICE_DECISION = {"DA-4401-": 85999}
# Keputusan owner 2026-09-12: qty "465 kg"/"930 kg" per potong di DA-2101 = 0,465 / 0,93 kg.
# Baris ini sudah dikeluarkan dari 10_BOM sumber (ada di DAFTAR_PERBAIKAN), jadi ditambahkan kembali.
BOM_CORRECTIONS = [
    ("DA-2101", "ALLSIZE", w, f"KN-K24-{w}", q, "kg")
    for w, q in (("CRL", 0.465), ("MNT", 0.465), ("BRG", 0.93), ("HTM", 0.465),
                 ("JBL", 0.465), ("TRC", 0.465), ("MHG", 0.465), ("MCA", 0.465))
]


def _price(v) -> int | None:
    try:
        return int(round(float(str(v).replace(".", "").replace(",", ".")))) if str(v).count(",") else int(round(float(v)))
    except (TypeError, ValueError):
        return None


def header_map(ws) -> dict[str, int]:
    return {str(c.value).strip().lower(): i for i, c in enumerate(ws[1], start=1) if c.value}


def fill_location_roles(wb, notes: list) -> None:
    ws = wb["01_LOKASI"]
    h = header_map(ws)
    if "peran" not in h:
        ws.cell(row=1, column=ws.max_column + 1, value="peran")
        h = header_map(ws)
    seen = set()
    for row in ws.iter_rows(min_row=2):
        code = str(row[h["kode"] - 1].value or "").strip().upper()
        if code in PERAN:
            row[h["peran"] - 1].value = PERAN[code]
            seen.add(code)
            notes.append(["01_LOKASI", "Peran lokasi diisi (keputusan owner)", code, 1,
                          f"peran = {PERAN[code]}; kode ZNA-* bawaan sistem tidak dipakai lagi"])
    missing = set(PERAN) - seen
    if missing:
        raise SystemExit(f"Kode lokasi untuk peran tidak ada di sheet: {sorted(missing)}")


def extract_catalog_conflicts(wb, notes: list) -> int:
    ws = wb["14_KATALOG_JUAL"]
    h = header_map(ws)
    groups: dict[tuple, list[int]] = defaultdict(list)
    values: dict[int, tuple] = {}
    for row in ws.iter_rows(min_row=2):
        r = row[0].row
        ak = str(row[h["kode_akun"] - 1].value or "").strip().upper()
        sku = str(row[h["sku"] - 1].value or "").strip().upper()
        if not ak and not sku:
            continue
        values[r] = tuple(str(row[h[k] - 1].value or "").strip() if k in h else "" for k in CAT_KEYS)
        groups[(ak, sku)].append(r)
    drop: list[int] = []
    for (ak, sku), rows in groups.items():
        if len(rows) > 1 and len({values[r] for r in rows}) > 1:
            harga = sorted({values[r][0] for r in rows})
            decided = next((p for pre, p in CATALOG_PRICE_DECISION.items() if sku.startswith(pre)), None)
            if decided is not None:
                keep = [r for r in rows if _price(values[r][0]) == decided]
                if keep:
                    for r in rows:
                        if r not in keep:
                            drop.append(r)
                    notes.append(["14_KATALOG_JUAL", "KONFLIK harga toko–SKU — DIPUTUSKAN owner 2026-09-12",
                                  f"{ak} / {sku}", len(rows) - len(keep),
                                  f"Dipakai Rp {decided:,}; baris {' vs '.join(harga)} lainnya dibuang."])
                    continue
            for r in rows:
                drop.append(r)
                notes.append(["14_KATALOG_JUAL", "KONFLIK harga toko–SKU — DIKELUARKAN, menunggu jawaban klien",
                              f"{ak} / {sku} (baris asli {r})", 1,
                              f"Harga mana yang benar: {' vs '.join(harga)}? Tautan berbeda → kemungkinan listing "
                              "satuan vs bundel; bila keduanya sah, bundel perlu SKU sendiri."])
    for r in sorted(drop, reverse=True):
        ws.delete_rows(r, 1)
    return len(drop)


def append_bom_corrections(wb, notes: list) -> int:
    ws = wb["10_BOM"]
    h = header_map(ws)
    existing = {tuple(str(row[h[k] - 1].value or "").strip().upper()
                      for k in ("kode_model", "kode_ukuran", "kode_warna", "kode_material"))
                for row in ws.iter_rows(min_row=2)}
    added = 0
    for model, size, color, mat, qty, unit in BOM_CORRECTIONS:
        if (model, size, color, mat) in existing:
            continue
        rec = {"kode_model": model, "kode_ukuran": size, "kode_warna": color, "kode_material": mat,
               "qty_per_pcs": qty, "satuan": unit, "keterangan": "koreksi owner 2026-09-12: 465 kg → 0,465 kg"}
        ws.append([rec.get(k) for k, _ in sorted(h.items(), key=lambda kv: kv[1])])
        notes.append(["10_BOM", "qty MUSTAHIL — DIKOREKSI owner 2026-09-12",
                      f"{model} / {size} / {color} / {mat}", 1, f"qty_per_pcs = {qty} {unit}"])
        added += 1
    return added


def main(src: Path, dest: Path) -> None:
    if dest.exists():
        raise SystemExit(f"Tujuan sudah ada: {dest}")
    wb = load_workbook(src)
    notes: list = []
    fill_location_roles(wb, notes)
    dropped = extract_catalog_conflicts(wb, notes)
    bom_added = append_bom_corrections(wb, notes)
    if "DAFTAR_PERBAIKAN" not in wb.sheetnames:
        ws = wb.create_sheet("DAFTAR_PERBAIKAN")
        ws.append(["Sheet", "Perkara", "Kode / baris", "Jumlah baris", "Pertanyaan"])
    ws = wb["DAFTAR_PERBAIKAN"]
    for n in notes:
        ws.append(n)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    print(f"Salinan go-live: {dest}\n  peran lokasi diisi : {len(PERAN)}\n  baris katalog konflik dikeluarkan: {dropped}"
          f"\n  baris BOM koreksi ditambahkan : {bom_added}"
          f"\n  catatan DAFTAR_PERBAIKAN ditambah : {len(notes)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
