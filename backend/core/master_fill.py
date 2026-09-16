"""core.master_fill — JALAN PINTAS PENGISIAN DATA yang hanya bisa diberi manusia (owner 2026-09-12):
1. BOM: salin BOM ke varian yang belum punya (potongan & kain otomatis diganti warna/ukuran tujuan) +
   tambah baris aksesoris ke SEMUA BOM aktif satu model.
2. Template Excel "Harga · Satuan · Rekening": harga & isi per satuan beli tiap material, no. rekening/atas nama bank,
   rekening pencairan per toko → unggah → pratinjau → terapkan.
3. Biaya standar potongan (qty kain jejak impor × harga kain) selama belum ada cutting nyata, lalu HPP semua model
   diterapkan lewat core.product_costing.apply_model_cost (SSOT HPP).
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import openpyxl
from openpyxl.styles import Font, PatternFill

from core.cut_panel_master import ensure_panel, bom_line_for_panel

_HDR, _FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")


def _now():
    return datetime.now(timezone.utc)


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, str):
        s = v.strip().replace("Rp", "").replace(" ", "")
        if s.count(".") > 1 or (s.count(".") == 1 and "," in s):
            s = s.replace(".", "")
        s = s.replace(",", ".")
        return float(s or 0)
    return float(v)


# ═══════════════════════════════════════════════════════════════════════════
# 1. BOM SHORTCUTS
# ═══════════════════════════════════════════════════════════════════════════
async def _fabric_for_color(db, src_code: str, color_code: str):
    """KN-K24-BRG → KN-K24-<WARNA TUJUAN> bila ada di master kain."""
    if not src_code or "-" not in src_code:
        return None
    fam = src_code.rsplit("-", 1)[0]
    return await db.rahaza_materials.find_one({"code": f"{fam}-{color_code}".upper(), "type": "fabric", "active": {"$ne": False}}, {"_id": 0})


async def bom_copy_to_missing(db, user: dict | None, model_id: str | None = None) -> dict:
    q = {"active": True}
    if model_id:
        q["model_id"] = model_id
    variants = await db.rahaza_model_variants.find(q, {"_id": 0}).to_list(20000)
    boms = await db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True, **({"model_id": model_id} if model_id else {})}, {"_id": 0}).to_list(20000)
    bom_key = {(b["model_id"], b.get("size_id"), (b.get("color_code") or "").upper()): b for b in boms}
    by_model: dict = {}
    for b in boms:
        by_model.setdefault(b["model_id"], []).append(b)
    created, skipped = [], []
    models = {m["id"]: m for m in await db.rahaza_models.find({}, {"_id": 0, "sop_steps": 0}).to_list(5000)}
    colors = {(c.get("code") or "").upper(): c for c in await db.rahaza_colors.find({}, {"_id": 0}).to_list(2000)}
    for v in variants:
        key = (v["model_id"], v.get("size_id"), (v.get("color_code") or "").upper())
        if key in bom_key:
            continue
        cands = by_model.get(v["model_id"]) or []
        if not cands:
            skipped.append({"sku": v["sku"], "reason": "model belum punya BOM sama sekali"})
            continue
        src = next((b for b in cands if b.get("size_id") == v.get("size_id")), None) or next((b for b in cands if (b.get("color_code") or "").upper() == key[2]), None) or cands[0]
        model = models.get(v["model_id"]) or {}
        color_name = (colors.get(key[2]) or {}).get("name") or v.get("color_name") or key[2]
        lines, notes = [], []
        for ln in src.get("materials") or []:
            if ln.get("is_cut_panel"):
                src_fab = None
                if ln.get("source_material_code"):
                    src_fab = await _fabric_for_color(db, ln["source_material_code"], key[2]) or await db.rahaza_materials.find_one({"code": ln["source_material_code"]}, {"_id": 0})
                panel, _new = await ensure_panel(db, model=model, color_code=key[2], color_name=color_name, size_code=v["size_code"],
                                                 size_id=v.get("size_id"), source_fabric=src_fab, created_from="bom_copy")
                new_line = bom_line_for_panel(panel, ln)
                new_line["qty"] = ln.get("qty") or 1.0
                lines.append(new_line)
                if src_fab is None and ln.get("source_material_code"):
                    notes.append(f"kain {ln['source_material_code']} warna {key[2]} belum ada di master")
            elif (ln.get("material_type") or "").lower() == "fabric":
                fab = await _fabric_for_color(db, ln.get("code") or "", key[2])
                if fab:
                    lines.append({**ln, "material_id": fab["id"], "code": fab["code"], "name": fab["name"], "unit_cost_base": float(fab.get("unit_cost") or 0)})
                else:
                    lines.append(dict(ln))
                    notes.append(f"kain {ln.get('code')} dipakai apa adanya (belum ada varian warna {key[2]})")
            else:
                lines.append(dict(ln))
        doc = {"id": str(uuid.uuid4()), "model_id": v["model_id"], "size_id": v.get("size_id"), "color": color_name, "color_code": key[2],
               "version": 1, "is_active": True, "active": True, "materials": lines,
               "notes": f"Disalin dari BOM {src.get('color_code') or src.get('color')}/{src.get('size_id') == v.get('size_id') and 'ukuran sama' or 'ukuran lain'}"
                        + (" · " + "; ".join(notes) if notes else ""),
               "copied_from_bom_id": src["id"], "created_by": (user or {}).get("id", "system"), "created_at": _now(), "updated_at": _now()}
        await db.rahaza_boms.insert_one(doc)
        bom_key[key] = doc
        by_model.setdefault(v["model_id"], []).append(doc)
        created.append({"sku": v["sku"], "lines": len(lines), "notes": notes})
    return {"created": len(created), "skipped": skipped, "detail": created[:200]}


async def bom_add_lines_to_model(db, user: dict | None, model_id: str, lines: list) -> dict:
    from routes.rahaza_bom import resolve_bom_materials
    resolved, problems = await resolve_bom_materials(db, lines)
    boms = await db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}, "is_active": True}, {"_id": 0}).to_list(2000)
    touched, appended = 0, 0
    for b in boms:
        have = {(ln.get("material_id") or ln.get("code")) for ln in b.get("materials") or []}
        add = [dict(r) for r in resolved if (r.get("material_id") or r.get("code")) not in have]
        if not add:
            continue
        await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": (b.get("materials") or []) + add, "updated_at": _now()},
                                                          "$push": {"change_log": {"at": _now(), "by": (user or {}).get("name", "system"), "note": f"+{len(add)} aksesoris (massal)"}}})
        touched += 1
        appended += len(add)
    return {"boms_touched": touched, "lines_appended": appended, "problems": problems, "boms_total": len(boms)}


# ═══════════════════════════════════════════════════════════════════════════
# 2. TEMPLATE HARGA · SATUAN · REKENING
# ═══════════════════════════════════════════════════════════════════════════
MAT_COLS = ["kode", "nama", "tipe", "kategori", "satuan_dasar", "satuan_beli", "isi_per_satuan_beli", "harga_per_satuan_beli", "harga_per_satuan_dasar_sekarang", "min_stok", "keterangan"]
REK_COLS = ["kode_akun", "nama_akun", "bank", "no_rekening", "atas_nama"]
TOKO_COLS = ["kode_toko", "nama_toko", "platform", "rekening_pencairan_kode_akun"]
BOM_COLS = ["kode_model", "nama_model", "kode_material", "nama_material", "qty_per_pcs", "satuan", "keterangan"]
MODEL_COLS = ["kode_model", "nama_model", "kategori", "berat_gram", "punya_bom", "punya_aksesoris", "keterangan"]
PETUNJUK = [
    "TEMPLATE HARGA · SATUAN · REKENING · BOM · MODEL — CV. Dewi Aditya",
    "Sheet MATERIAL: isi 'satuan_beli' (roll/pack/gross/kg/yard/pcs…), 'isi_per_satuan_beli' = berapa satuan dasar dalam 1 satuan beli",
    "   (contoh: bisban satuan dasar m, beli per roll isi 21,9 → isi 21.9; kancing dasar pcs, beli per gross isi 144).",
    "   'harga_per_satuan_beli' = harga 1 satuan beli. Sistem menghitung harga per satuan dasar = harga ÷ isi dan menyimpan konversi satuan.",
    "   Baris yang harganya dibiarkan kosong/0 TIDAK diubah. Potongan (CUT-…) tidak perlu diisi — biaya standarnya dihitung dari kain.",
    "Sheet REKENING: lengkapi no_rekening & atas_nama tiap akun bank/dompet (rekening Kas & Bank sudah tertaut ke akun ini).",
    "Sheet TOKO: isi 'rekening_pencairan_kode_akun' dgn kode akun bank tempat dana Shopee/TikTok cair (lihat daftar di sheet REKENING).",
    "Sheet BOM_AKSESORIS: satu baris = satu bahan/aksesoris untuk satu model (kode_model dari sheet MODEL, kode_material dari sheet MATERIAL),",
    "   'qty_per_pcs' = kebutuhan per 1 pcs jadi dalam satuan dasar material. Baris ditambahkan ke SEMUA BOM varian model itu (yang sudah ada dilewati);",
    "   model yang belum punya BOM dibuatkan BOM dasar lalu disalin ke tiap varian. Contoh baris sudah disiapkan per model — hapus yang tidak perlu.",
    "Sheet MODEL: isi 'berat_gram' (berat 1 pcs jadi, untuk ongkir). Kolom punya_bom/punya_aksesoris hanya informasi.",
    "Unggah di Portal Keuangan → Master Akuntansi → Impor Master (atau RnD → Master Produk → Harga & Satuan).",
]


def _head(ws, cols):
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = _HDR, _FILL


async def build_fill_template(db) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PETUNJUK"
    for r in PETUNJUK:
        ws.append([r])
    ws.column_dimensions["A"].width = 130
    ws = wb.create_sheet("MATERIAL")
    _head(ws, MAT_COLS)
    async for m in db.rahaza_materials.find({"type": {"$ne": "fg"}, "active": {"$ne": False}, "code": {"$not": {"$regex": "^CUT-"}}}, {"_id": 0}).sort("code", 1):
        ws.append([m.get("code"), m.get("name"), m.get("type"), m.get("category_name"), m.get("unit"), m.get("purchase_uom") or m.get("pack_unit") or m.get("unit"),
                   m.get("pack_size") if (m.get("pack_unit") and m.get("pack_unit") != m.get("unit")) else 1, None, float(m.get("unit_cost") or 0), float(m.get("min_stock") or 0), ""])
    for col, w in zip("ABCDEFGHIJK", (14, 44, 10, 16, 12, 12, 18, 20, 24, 10, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    ws = wb.create_sheet("REKENING")
    _head(ws, REK_COLS)
    async for r in db.rahaza_cash_accounts.find({"active": {"$ne": False}}, {"_id": 0}).sort("code", 1):
        ws.append([r.get("gl_account_code"), r.get("name"), r.get("bank_name"), r.get("account_number") or "", r.get("holder_name") or ""])
    for col, w in zip("ABCDE", (12, 40, 18, 22, 30)):
        ws.column_dimensions[col].width = w
    ws = wb.create_sheet("TOKO")
    _head(ws, TOKO_COLS)
    async for s in db.marketing_platform_accounts.find({"active": {"$ne": False}}, {"_id": 0}).sort("account_code", 1):
        ws.append([s.get("account_code"), s.get("account_name"), s.get("platform"), s.get("coa_cash_code") or ""])
    for col, w in zip("ABCD", (12, 30, 12, 28)):
        ws.column_dimensions[col].width = w
    # ── BOM_AKSESORIS & MODEL: kekurangan yang dilaporkan Papan Kelengkapan RnD ──
    models = await db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "category_name": 1, "weight_gram": 1}).sort("code", 1).to_list(5000)
    has_bom, has_acc = set(), set()
    async for b in db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True}, {"_id": 0, "model_id": 1, "materials": 1}):
        has_bom.add(b["model_id"])
        if any((ln.get("material_type") or "").lower() not in ("fabric", "") and not ln.get("is_cut_panel") for ln in b.get("materials") or []):
            has_acc.add(b["model_id"])
    ws = wb.create_sheet("BOM_AKSESORIS")
    _head(ws, BOM_COLS)
    for m in models:
        ws.append([m.get("code"), m.get("name"), "", "", None, "", "" if m["id"] in has_acc else "belum ada aksesoris — isi kode_material & qty"])
    for col, w in zip("ABCDEFG", (14, 30, 16, 36, 12, 10, 40)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    ws = wb.create_sheet("MODEL")
    _head(ws, MODEL_COLS)
    for m in models:
        ws.append([m.get("code"), m.get("name"), m.get("category_name"), float(m.get("weight_gram") or 0) or None,
                   "ya" if m["id"] in has_bom else "BELUM", "ya" if m["id"] in has_acc else "BELUM", ""])
    for col, w in zip("ABCDEFG", (14, 30, 16, 12, 12, 16, 40)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def parse_fill_workbook(db, data: bytes) -> dict:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errors": [f"Berkas bukan .xlsx valid: {e}"], "materials": [], "accounts": [], "stores": []}
    errors, mats, accs, stores = [], [], [], []
    from core.fin_statements import cash_account_codes
    cash_codes = await cash_account_codes(db)
    if "MATERIAL" in wb.sheetnames:
        codes = {m["code"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}}, {"_id": 0, "code": 1, "unit": 1, "unit_cost": 1, "name": 1, "min_stock": 1}).to_list(20000)}
        for i, r in enumerate(wb["MATERIAL"].iter_rows(values_only=True, min_row=2), start=2):
            if not r or not r[0]:
                continue
            code = str(r[0]).strip()
            m = codes.get(code)
            if not m:
                errors.append(f"MATERIAL baris {i}: kode {code} tidak ada")
                continue
            try:
                buy_unit = (str(r[5]).strip().lower() if len(r) > 5 and r[5] else m["unit"])
                isi = _num(r[6]) if len(r) > 6 else 0
                harga_beli = _num(r[7]) if len(r) > 7 else 0
                min_stok = _num(r[9]) if len(r) > 9 else 0
            except ValueError:
                errors.append(f"MATERIAL baris {i}: {code} angka tidak valid")
                continue
            min_changed = min_stok > 0 and abs(min_stok - float(m.get("min_stock") or 0)) > 1e-9
            if harga_beli <= 0 and not min_changed:
                continue
            if harga_beli > 0 and isi <= 0:
                if buy_unit == m["unit"]:
                    isi = 1
                else:
                    errors.append(f"MATERIAL baris {i}: {code} isi_per_satuan_beli wajib > 0 untuk satuan beli {buy_unit}")
                    continue
            mats.append({"code": code, "name": m["name"], "base_unit": m["unit"], "buy_unit": buy_unit, "pack_size": isi or 1, "buy_price": harga_beli,
                         "unit_cost": round(harga_beli / (isi or 1), 4) if harga_beli > 0 else None, "unit_cost_before": float(m.get("unit_cost") or 0), "min_stock": min_stok if min_changed else None})
    if "REKENING" in wb.sheetnames:
        for i, r in enumerate(wb["REKENING"].iter_rows(values_only=True, min_row=2), start=2):
            if not r or not r[0]:
                continue
            code = str(r[0]).strip()
            if code not in cash_codes:
                errors.append(f"REKENING baris {i}: {code} bukan akun kas/bank")
                continue
            no, nama = (str(r[3]).strip() if len(r) > 3 and r[3] else ""), (str(r[4]).strip() if len(r) > 4 and r[4] else "")
            if no or nama:
                accs.append({"gl_account_code": code, "account_number": no, "holder_name": nama, "bank_name": str(r[2]).strip() if len(r) > 2 and r[2] else ""})
    if "TOKO" in wb.sheetnames:
        store_codes = {s["account_code"] for s in await db.marketing_platform_accounts.find({}, {"_id": 0, "account_code": 1}).to_list(500)}
        for i, r in enumerate(wb["TOKO"].iter_rows(values_only=True, min_row=2), start=2):
            if not r or not r[0]:
                continue
            code, bank = str(r[0]).strip(), (str(r[3]).strip() if len(r) > 3 and r[3] else "")
            if code not in store_codes:
                errors.append(f"TOKO baris {i}: toko {code} tidak ada")
            elif bank and bank not in cash_codes:
                errors.append(f"TOKO baris {i}: {bank} bukan akun kas/bank")
            elif bank:
                stores.append({"account_code": code, "coa_cash_code": bank})
    bom_rows, model_rows = [], []
    if "BOM_AKSESORIS" in wb.sheetnames or "MODEL" in wb.sheetnames:
        models = {m["code"]: m for m in await db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "weight_gram": 1}).to_list(5000)}
    if "BOM_AKSESORIS" in wb.sheetnames:
        mat_master = {m["code"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}, "active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "type": 1}).to_list(20000)}
        for i, r in enumerate(wb["BOM_AKSESORIS"].iter_rows(values_only=True, min_row=2), start=2):
            if not r or not r[0]:
                continue
            mcode = str(r[0]).strip()
            matcode = str(r[2]).strip().upper() if len(r) > 2 and r[2] else ""
            if not matcode:
                continue  # baris contoh yang tidak diisi
            if mcode not in models:
                errors.append(f"BOM_AKSESORIS baris {i}: model {mcode} tidak ada")
                continue
            mat = mat_master.get(matcode)
            if not mat:
                errors.append(f"BOM_AKSESORIS baris {i}: material {matcode} tidak ada di master (lihat sheet MATERIAL)")
                continue
            try:
                qty = _num(r[4]) if len(r) > 4 else 0
            except ValueError:
                errors.append(f"BOM_AKSESORIS baris {i}: qty_per_pcs bukan angka")
                continue
            if qty <= 0:
                errors.append(f"BOM_AKSESORIS baris {i}: qty_per_pcs {mcode}/{matcode} wajib > 0")
                continue
            bom_rows.append({"model_code": mcode, "model_id": models[mcode]["id"], "code": mat["code"], "material_id": mat["id"], "name": mat["name"],
                             "qty": qty, "unit": (str(r[5]).strip() if len(r) > 5 and r[5] else mat.get("unit")), "material_type": mat.get("type")})
    if "MODEL" in wb.sheetnames:
        for i, r in enumerate(wb["MODEL"].iter_rows(values_only=True, min_row=2), start=2):
            if not r or not r[0]:
                continue
            mcode = str(r[0]).strip()
            if mcode not in models:
                errors.append(f"MODEL baris {i}: model {mcode} tidak ada")
                continue
            try:
                berat = _num(r[3]) if len(r) > 3 else 0
            except ValueError:
                errors.append(f"MODEL baris {i}: berat_gram bukan angka")
                continue
            if berat > 0 and abs(berat - float(models[mcode].get("weight_gram") or 0)) > 1e-9:
                model_rows.append({"model_code": mcode, "model_id": models[mcode]["id"], "weight_gram": berat})
    return {"ok": not errors, "errors": errors, "materials": mats, "accounts": accs, "stores": stores, "bom_lines": bom_rows, "models": model_rows,
            "totals": {"materials": len(mats), "accounts": len(accs), "stores": len(stores), "bom_lines": len(bom_rows),
                       "bom_models": len({b["model_id"] for b in bom_rows}), "models": len(model_rows)}}


async def apply_fill(db, parsed: dict, user: dict | None) -> dict:
    from core.master_sync import _sync_units
    n_mat = 0
    for m in parsed["materials"]:
        patch = {"updated_at": _now()}
        if m.get("unit_cost") is not None:
            patch.update({"unit_cost": m["unit_cost"], "cost_method": "moving_average", "cost_source": "harga_awal_owner", "purchase_uom": m["buy_unit"],
                          "pack_unit": m["buy_unit"], "pack_size": m["pack_size"], "price_updated_at": _now(),
                          "uoms": [{"code": m["base_unit"], "name": m["base_unit"].upper(), "factor": 1.0, "is_base": True, "level": 0}]
                          + ([{"code": m["buy_unit"], "name": m["buy_unit"].upper(), "factor": m["pack_size"], "is_base": False, "level": 1}] if m["buy_unit"] != m["base_unit"] else [])})
        if m.get("min_stock") is not None:
            patch["min_stock"] = m["min_stock"]
        await db.rahaza_materials.update_one({"code": m["code"]}, {"$set": patch})
        if m.get("unit_cost") is not None:
            await db.rahaza_material_cost_history.insert_one({"id": str(uuid.uuid4()), "material_code": m["code"], "unit_cost": m["unit_cost"], "before": m["unit_cost_before"],
                                                              "source": "template_harga_owner", "by": (user or {}).get("name", "system"), "at": _now()})
        n_mat += 1
    for a in parsed["accounts"]:
        p = {"account_number": a["account_number"], "holder_name": a["holder_name"], "updated_at": _now()}
        if a.get("bank_name"):
            p["bank_name"] = a["bank_name"]
        await db.rahaza_cash_accounts.update_one({"gl_account_code": a["gl_account_code"]}, {"$set": p})
    for s in parsed["stores"]:
        await db.marketing_platform_accounts.update_one({"account_code": s["account_code"]}, {"$set": {"coa_cash_code": s["coa_cash_code"], "updated_at": _now()}})
    bom_res = await apply_bom_lines(db, parsed.get("bom_lines") or [], user)
    for m in parsed.get("models") or []:
        await db.rahaza_models.update_one({"id": m["model_id"]}, {"$set": {"weight_gram": m["weight_gram"], "updated_at": _now()}})
    rep: dict = {}
    await _sync_units(db, rep)
    hpp = await recalc_standard_costs(db, user)
    return {"materials_updated": n_mat, "accounts_updated": len(parsed["accounts"]), "stores_updated": len(parsed["stores"]),
            "models_weight_updated": len(parsed.get("models") or []), **bom_res, "units_added": rep.get("units_added"), **hpp}


async def apply_bom_lines(db, rows: list, user: dict | None) -> dict:
    """Baris BOM_AKSESORIS per model → tambah ke semua BOM varian; model tanpa BOM dibuatkan BOM dasar lalu disalin ke variannya."""
    by_model: dict = {}
    for r in rows:
        by_model.setdefault(r["model_id"], []).append(r)
    touched, appended, created_base, problems = 0, 0, 0, []
    for model_id, lines in by_model.items():
        has = await db.rahaza_boms.count_documents({"model_id": model_id, "active": {"$ne": False}, "is_active": True})
        if not has:
            from routes.rahaza_bom import resolve_bom_materials
            resolved, prob = await resolve_bom_materials(db, [{"material_id": ln["material_id"], "code": ln["code"], "qty": ln["qty"], "unit": ln["unit"]} for ln in lines], strict_accessory=False)
            problems += prob
            v = await db.rahaza_model_variants.find_one({"model_id": model_id, "active": True}, {"_id": 0, "color_code": 1, "color_name": 1, "size_id": 1})
            await db.rahaza_boms.insert_one({"id": str(uuid.uuid4()), "model_id": model_id, "size_id": (v or {}).get("size_id"), "color": (v or {}).get("color_name"),
                                             "color_code": ((v or {}).get("color_code") or "").upper() or None, "version": 1, "is_active": True, "active": True,
                                             "materials": resolved, "notes": "BOM dasar dari template BOM_AKSESORIS", "created_by": (user or {}).get("id", "system"),
                                             "created_at": _now(), "updated_at": _now()})
            created_base += 1
            await bom_copy_to_missing(db, user, model_id)
            continue
        res = await bom_add_lines_to_model(db, user, model_id, [{"material_id": ln["material_id"], "code": ln["code"], "qty": ln["qty"], "unit": ln["unit"]} for ln in lines])
        touched += res["boms_touched"]
        appended += res["lines_appended"]
        problems += res.get("problems") or []
    return {"bom_models": len(by_model), "bom_base_created": created_base, "boms_touched": touched, "bom_lines_appended": appended, "bom_problems": problems[:20]}


# ═══════════════════════════════════════════════════════════════════════════
# 3. BIAYA STANDAR POTONGAN + HPP SEMUA MODEL
# ═══════════════════════════════════════════════════════════════════════════
async def recalc_standard_costs(db, user: dict | None) -> dict:
    """Potongan tanpa nilai aktual: unit_cost = qty kain (jejak impor / BOM salinan) × harga kain sumber. Aktual cutting menimpa."""
    fabrics = {m["code"]: m for m in await db.rahaza_materials.find({"type": "fabric", "code": {"$not": {"$regex": "^CUT-"}}}, {"_id": 0, "code": 1, "id": 1, "unit_cost": 1}).to_list(5000)}
    fab_by_id = {m["id"]: m for m in fabrics.values()}
    qty_by_panel: dict = {}
    async for b in db.rahaza_boms.find({"active": {"$ne": False}}, {"_id": 0, "materials": 1}):
        for ln in b.get("materials") or []:
            if ln.get("is_cut_panel") and ln.get("material_id"):
                mf = ln.get("migrated_from_fabric") or {}
                qty_by_panel.setdefault(ln["material_id"], (float(mf.get("qty") or 0), mf.get("code") or ln.get("source_material_code")))
    updated = 0
    async for p in db.rahaza_materials.find({"code": {"$regex": "^CUT-"}, "value_status": {"$ne": "actual"}}, {"_id": 0, "id": 1, "source_material_code": 1, "source_material_id": 1, "unit_cost": 1}):
        qty, fcode = qty_by_panel.get(p["id"], (0.0, None))
        fab = fabrics.get(p.get("source_material_code") or fcode or "") or fab_by_id.get(p.get("source_material_id") or "")
        if not fab or not qty:
            continue
        std = round(qty * float(fab.get("unit_cost") or 0), 2)
        if std <= 0 or abs(std - float(p.get("unit_cost") or 0)) < 0.005:
            continue
        await db.rahaza_materials.update_one({"id": p["id"]}, {"$set": {"unit_cost": std, "value_status": "standard", "standard_cost_basis": {"fabric_code": fab["code"], "qty": qty, "fabric_unit_cost": fab.get("unit_cost")},
                                                              "value_note": f"Biaya STANDAR: {qty} × Rp {float(fab.get('unit_cost') or 0):,.0f} ({fab['code']}) — diganti nilai nyata saat cutting pertama.", "updated_at": _now()}})
        updated += 1
    # baris BOM ikut harga master
    async for b in db.rahaza_boms.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "materials": 1}):
        ids = [ln.get("material_id") for ln in b.get("materials") or [] if ln.get("material_id")]
        costs = {m["id"]: float(m.get("unit_cost") or 0) async for m in db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "unit_cost": 1})}
        new = [{**ln, "unit_cost_base": costs.get(ln.get("material_id"), ln.get("unit_cost_base") or 0)} for ln in b.get("materials") or []]
        if new != (b.get("materials") or []):
            await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": new, "updated_at": _now()}})
    from core.product_costing import apply_model_cost
    applied, failed = 0, []
    async for m in db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1}):
        try:
            res = await apply_model_cost(db, m["id"], user or {"id": "system", "name": "master_fill"})
            if res.get("applied"):
                applied += 1
        except Exception as e:  # noqa: BLE001
            failed.append(f"{m['code']}: {str(e)[:80]}")
    return {"panels_standard_costed": updated, "models_hpp_applied": applied, "models_hpp_failed": failed[:10]}
