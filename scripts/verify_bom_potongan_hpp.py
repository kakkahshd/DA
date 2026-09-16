#!/usr/bin/env python3
"""verify_bom_potongan_hpp.py — GATE **INV-F46** (2026-09-12).
"BOM MEMAKAI POTONGAN; BIAYA POTONGAN = KAIN ROLL YANG DIPOTONG ÷ PCS; HPP IKUT."

Contoh owner: 1 roll 150 yard seharga Rp 3.000.000 → dipotong jadi 150 potongan →
Rp 20.000/potongan → HPP bahan produk = Rp 20.000 (bukan "0,465 kg × harga").

INVARIAN
  P1  Semua BOM aktif menyebut POTONGAN (1 pcs), TIDAK ada baris kain roll (kg/yard)
  P2  Master potongan = 1 per model × warna × ukuran, kode CUT-<MODEL>-<WARNA>-<UKURAN>,
      menunjuk kain asal (`source_material_code`)
  P3  Sebelum cutting: HPP bahan JUJUR Rp 0 + gap `panel_unvalued` (bukan ditebak)
  P4  Order Cutting untuk model+ukuran+warna BOM otomatis menunjuk potongan BOM itu
  P5  Progres cutting 150 yard (Rp 3.000.000) → 150 pcs ⇒ potongan Rp 20.000/pcs,
      stok potongan +150, stok kain −150
  P6  HPP bahan produk (kalkulator) = Rp 20.000 — dari potongan, bukan dari kg kain
  P7  Rencana cutting: BOM potongan ⇒ `plan_manual` (tidak menebak kg)
  P8  Bersih-bersih: semua artefak uji hilang, stok & biaya potongan kembali
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from lib.gr_common import login  # noqa: E402

API = os.environ.get("API_BASE", "http://localhost:8001")
G, R, C, B, X = "\033[92m", "\033[91m", "\033[96m", "\033[1m", "\033[0m"
PASS: list[str] = []
FAIL: list[str] = []
STAMP = time.strftime("F46%H%M%S")
MAT_CODE = f"GATE-KAIN-{STAMP}"


def ok(k, m, d=""):
    PASS.append(k); print(f"  {G}✓{X} {k} {m}" + (f" · {d}" if d else ""))


def bad(k, m, d=""):
    FAIL.append(k); print(f"  {R}✗{X} {k} {m}" + (f" · {d}" if d else ""))


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:  # noqa: BLE001
            return e.code, None


def env():
    out = {}
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def main() -> int:
    from pymongo import MongoClient
    e = env()
    db = MongoClient(e["MONGO_URL"])[e["DB_NAME"]]
    token = login()
    print(f"{B}{C}INV-F46 — BOM POTONGAN & HPP DARI KAIN YANG DIPOTONG{X}")

    # ── P1 / P2 ─────────────────────────────────────────────────────────────
    boms = list(db.rahaza_boms.find({"active": True, "is_active": True}, {"_id": 0}))
    kain_lines = sum(1 for b in boms for m in b.get("materials", [])
                     if m.get("material_type") == "fabric" and not m.get("is_cut_panel"))
    panel_lines = sum(1 for b in boms for m in b.get("materials", []) if m.get("is_cut_panel"))
    if boms and kain_lines == 0 and panel_lines == len(boms):
        ok("P1", "semua BOM aktif memakai 1 pcs potongan, tanpa baris kain roll",
           f"{len(boms)} BOM · {panel_lines} baris potongan · {kain_lines} baris kain")
    else:
        bad("P1", "masih ada BOM yang memakai kain roll (kg/yard) sebagai bahan",
            f"{len(boms)} BOM · potongan={panel_lines} · kain={kain_lines}")

    panels = {p["id"]: p for p in db.rahaza_materials.find({"is_cut_panel": True, "active": True}, {"_id": 0})}
    bad_codes = []
    for b in boms:
        for m in b.get("materials", []):
            if not m.get("is_cut_panel"):
                continue
            p = panels.get(m.get("material_id"))
            model = db.rahaza_models.find_one({"id": b["model_id"]}, {"_id": 0, "code": 1}) or {}
            size = db.rahaza_sizes.find_one({"id": b["size_id"]}, {"_id": 0, "code": 1}) or {}
            want = f"CUT-{model.get('code')}-{b.get('color_code')}-{size.get('code')}".upper()
            if not p or p.get("code") != want or not p.get("source_material_code"):
                bad_codes.append(f"{(p or {}).get('code')}≠{want}")
    if not bad_codes:
        ok("P2", "kode potongan = CUT-<MODEL>-<WARNA>-<UKURAN> & menunjuk kain asal",
           f"{len(panels)} master potongan")
    else:
        bad("P2", "kode potongan tidak sesuai model×warna×ukuran BOM", "; ".join(bad_codes[:4]))

    # pilih satu BOM nyata untuk skenario owner
    target = next((b for b in boms if any(m.get("is_cut_panel") for m in b["materials"])), None)
    if not target:
        bad("P3", "tidak ada BOM potongan untuk diuji"); return finish()
    panel = panels[next(m["material_id"] for m in target["materials"] if m.get("is_cut_panel"))]
    model = db.rahaza_models.find_one({"id": target["model_id"]}, {"_id": 0})
    size = db.rahaza_sizes.find_one({"id": target["size_id"]}, {"_id": 0})
    color = db.rahaza_colors.find_one({"code": target.get("color_code")}, {"_id": 0}) or {}
    panel_before = dict(panel)

    st, cost0 = call("GET", f"/api/costing/models/{model['id']}", token)
    gaps0 = [g["code"] for g in (cost0 or {}).get("gaps", [])]
    sz0 = next((s for s in (cost0 or {}).get("sizes", []) if s.get("size_id") == size["id"]), {}) or {}
    mat0 = (sz0.get("material") or {}).get("material_cost", sz0.get("material_cost"))
    if st == 200 and "panel_unvalued" in gaps0 and float(mat0 or 0) == 0:
        ok("P3", "sebelum cutting: HPP bahan Rp 0 + gap panel_unvalued (jujur, tidak ditebak)",
           f"{model['code']} {size['code']} {target.get('color_code')} → {panel['code']}")
    else:
        bad("P3", "HPP bahan sebelum cutting tidak jujur", f"HTTP {st} bahan={mat0} gaps={gaps0[:6]}")

    # ── data uji: kain roll 150 yard @ Rp 20.000 (= Rp 3.000.000) ───────────
    st, d = call("GET", "/api/rahaza/storage-locations", token)
    locs = d if isinstance(d, list) else (d or {}).get("items") or []
    loc = next((x for x in locs if "kain" in str(x.get("name", "")).lower()), None) or (locs[0] if locs else None)
    if not loc:
        bad("P5", "tidak ada storage location"); return finish()
    st, d = call("POST", "/api/rahaza/materials", token, {
        "code": MAT_CODE, "name": f"Kain roll uji owner {STAMP}", "unit": "yard",
        "type": "fabric", "color": color.get("name") or target.get("color_code"), "unit_cost": 0,
        "notes": "gate INV-F46"})
    mat = (d or {}).get("material") or d
    if st not in (200, 201) or not mat or not mat.get("id"):
        bad("P5", "gagal membuat kain uji", str(d)[:200]); return finish()
    st, gr = call("POST", "/api/wms/legacy/receiving", token, {
        "source_type": "supplier", "supplier_name": "PT Gate F46",
        "location_id": loc.get("id"), "location_name": loc.get("name"), "notes": "gate INV-F46",
        "items": [{"product_name": mat["name"], "sku": mat["code"], "material_id": mat["id"],
                   "expected_qty": 150, "received_qty": 150, "rejected_qty": 0, "unit": "yard",
                   "unit_price": 20000, "inspection_status": "passed", "lot_number": "LOT-F46",
                   "rolls": [{"qty": 150, "color_lot": "LOT-F46", "notes": ""}]}]})
    if st not in (200, 201):
        bad("P5", "gagal membuat penerimaan", str(gr)[:200]); return finish(db, mat)
    st, _ = call("PUT", f"/api/wms/legacy/receiving/{gr['id']}", token, {"status": "received"})
    rolls = list(db.wh_fabric_rolls.find({"source_receipt_id": gr["id"]}, {"_id": 0}))
    mat_db = db.rahaza_materials.find_one({"id": mat["id"]}, {"_id": 0})
    if st != 200 or len(rolls) != 1 or abs(float(mat_db.get("unit_cost") or 0) - 20000) > 0.01:
        bad("P5", "roll/harga kain dari PO tidak terbentuk",
            f"rolls={len(rolls)} unit_cost={mat_db.get('unit_cost')}"); return finish(db, mat, gr, rolls)

    # ── P4 / P7: order cutting utk model+ukuran+warna BOM ──────────────────
    st, req = call("GET", f"/api/cutting/bom-requirement?model_id={model['id']}&size_id={size['id']}"
                          f"&qty_pcs=150&input_material_id={mat['id']}", token)
    if st == 200 and req.get("plan_manual") and (req.get("panel") or {}).get("code") == panel["code"] \
            and not [g for g in req.get("gaps", []) if g["code"] in ("input_not_in_bom", "bom_without_fabric")]:
        ok("P7", "rencana cutting: BOM potongan ⇒ rencana kain manual, tanpa gap kain-tidak-di-BOM",
           (req.get("plan_note") or "")[:90])
    else:
        bad("P7", "bom-requirement salah paham BOM potongan",
            f"HTTP {st} plan_manual={req.get('plan_manual')} gaps={[g['code'] for g in req.get('gaps', [])]}")

    st, order = call("POST", "/api/cutting/orders", token, {
        "input_material_id": mat["id"], "planned_input_qty": 150, "planned_output_qty": 150,
        "model_id": model["id"], "size_id": size["id"], "output_color": color.get("name") or target.get("color_code"),
        "location_id": loc.get("id"), "roll_ids": [rolls[0]["id"]], "notes": "gate INV-F46"})
    if st not in (200, 201):
        bad("P4", "gagal membuat order cutting", str(order)[:300]); return finish(db, mat, gr, rolls)
    if order.get("output_material_id") == panel["id"] and order.get("output_from_bom"):
        ok("P4", "order cutting otomatis menunjuk potongan BOM", f"{order['number']} → {panel['code']}")
    else:
        bad("P4", "order cutting tidak menunjuk potongan BOM",
            f"output={order.get('output_material_code')} harap {panel['code']}")

    # ── P5: potong 150 yard → 150 pcs ───────────────────────────────────────
    st, _ = call("POST", f"/api/cutting/orders/{order['id']}/start", token)
    stok_kain0 = float(db.rahaza_material_stock.aggregate([{"$match": {"material_id": mat["id"]}},
                       {"$group": {"_id": None, "q": {"$sum": "$qty"}}}]).next().get("q") or 0) if st == 200 else 0
    st, prog = call("POST", f"/api/cutting/orders/{order['id']}/progress", token,
                    {"input_consumed": 150, "output_qty": 150, "waste_qty": 0,
                     "roll_ids": [rolls[0]["id"]], "note": "gate INV-F46"})
    p_after = db.rahaza_materials.find_one({"id": panel["id"]}, {"_id": 0})
    q_panel = sum(float(r.get("qty") or 0) for r in db.rahaza_material_stock.find({"material_id": panel["id"]}))
    q_kain = sum(float(r.get("qty") or 0) for r in db.rahaza_material_stock.find({"material_id": mat["id"]}))
    if st == 200 and abs(float(p_after.get("unit_cost") or 0) - 20000) < 0.01 and abs(q_panel - 150) < 1e-6 \
            and abs(stok_kain0 - q_kain - 150) < 1e-6:
        ok("P5", "150 yard (Rp 3.000.000) → 150 potongan ⇒ Rp 20.000/potongan; stok kain −150, potongan +150",
           f"unit_cost potongan={p_after.get('unit_cost'):,.0f} · status={p_after.get('value_status')}")
    else:
        bad("P5", "biaya/stok potongan tidak sesuai contoh owner",
            f"HTTP {st} unit_cost={p_after.get('unit_cost')} stok_potongan={q_panel} kain {stok_kain0}→{q_kain} {str(prog)[:160]}")
    call("POST", f"/api/cutting/orders/{order['id']}/complete", token)

    # ── P6: HPP bahan produk = Rp 20.000 ────────────────────────────────────
    st, cost1 = call("GET", f"/api/costing/models/{model['id']}", token)
    sz1 = next((s for s in (cost1 or {}).get("sizes", []) if s.get("size_id") == size["id"]), {}) or {}
    mat1 = (sz1.get("material") or {}).get("material_cost", sz1.get("material_cost"))
    line = next((ln for ln in ((sz1.get("material") or {}).get("lines") or sz1.get("lines") or [])
                 if ln.get("material_id") == panel["id"]), {})
    if st == 200 and abs(float(mat1 or 0) - 20000) < 0.01 and line.get("unit_base") == "pcs":
        ok("P6", "HPP bahan produk = Rp 20.000 dari potongan (1 pcs × biaya potongan)",
           f"{model['code']} {size['code']}: {line.get('code')} {line.get('qty_base')} {line.get('unit_base')} × {line.get('unit_cost'):,.0f}")
    else:
        bad("P6", "HPP bahan produk tidak mengikuti biaya potongan",
            f"HTTP {st} bahan={mat1} baris={ {k: line.get(k) for k in ('code', 'qty_base', 'unit_base', 'unit_cost')} }")

    return finish(db, mat, gr, rolls, order, panel_before)


def finish(db=None, mat=None, gr=None, rolls=None, order=None, panel_before=None) -> int:
    if db is not None and mat:
        ids = [mat["id"]]
        n = {}
        if order:
            n["progress"] = db.cutting_progress.delete_many({"cutting_order_id": order["id"]}).deleted_count
            n["order"] = db.cutting_orders.delete_many({"id": order["id"]}).deleted_count
            n["mi"] = db.rahaza_material_issues.delete_many(
                {"$or": [{"cutting_order_id": order["id"]}, {"notes": {"$regex": order["number"]}}]}).deleted_count
        if gr:
            n["gr"] = db.warehouse_receiving.delete_many({"id": gr["id"]}).deleted_count
        if rolls:
            db.wh_fabric_rolls.delete_many({"id": {"$in": [r["id"] for r in rolls]}})
            db.wh_fabric_roll_movements.delete_many({"roll_id": {"$in": [r["id"] for r in rolls]}})
        if panel_before:
            ids.append(panel_before["id"])
            db.rahaza_materials.update_one({"id": panel_before["id"]}, {"$set": {
                k: panel_before.get(k) for k in ("unit_cost", "value_status", "value_note", "value_source", "updated_at")}})
        for coll, field in (("rahaza_material_stock", "material_id"), ("rahaza_stock_ledger", "material_id"),
                            ("rahaza_material_movements", "material_id"), ("material_cost_history", "material_id"),
                            ("rahaza_material_cost_history", "material_id")):
            if coll in db.list_collection_names():
                n[coll] = db[coll].delete_many({field: {"$in": ids}}).deleted_count
        n["mat"] = db.rahaza_materials.delete_many({"id": mat["id"]}).deleted_count
        n["gl"] = db.rahaza_journal_entries.delete_many({"$or": [{"description": {"$regex": "F46"}},
                                                                 {"memo": {"$regex": "F46"}}]}).deleted_count
        left = db.rahaza_materials.count_documents({"code": MAT_CODE}) \
            + db.cutting_orders.count_documents({"notes": "gate INV-F46"}) \
            + db.rahaza_material_stock.count_documents({"material_id": {"$in": ids}, "qty": {"$ne": 0}})
        p_now = db.rahaza_materials.find_one({"id": panel_before["id"]}, {"_id": 0, "unit_cost": 1}) if panel_before else {}
        if left == 0 and (not panel_before or float((p_now or {}).get("unit_cost") or 0) == float(panel_before.get("unit_cost") or 0)):
            ok("P8", "artefak uji bersih; stok & biaya potongan kembali", " · ".join(f"{k}={v}" for k, v in n.items()))
        else:
            bad("P8", "artefak uji tertinggal", f"sisa={left} potongan.unit_cost={(p_now or {}).get('unit_cost')}")
    print()
    if FAIL:
        print(f"{R}{B}VERDICT MERAH — {len(FAIL)} invarian gagal: {', '.join(FAIL)}{X}")
        return 1
    print(f"{G}{B}VERDICT HIJAU — {len(PASS)} invarian BOM potongan & HPP terjaga{X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
