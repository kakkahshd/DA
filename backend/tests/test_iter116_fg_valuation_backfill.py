"""
Iter 116 — Backfill WIP→FG receipt CMT internal lama + laporan Nilai Persediaan FG (M-01).
Data sintetis (receipt selesai QC tanpa wip_fg_je_id, lapisan HPP, stok fg_internal, PO internal & maklon), dibersihkan sendiri.
"""
import os
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
db = MongoClient(os.environ.get("MONGO_URL") or be["MONGO_URL"])[os.environ.get("DB_NAME") or be["DB_NAME"]]
SFX = uuid.uuid4().hex[:6]
PO_INT, PO_MK = f"po-int-{SFX}", f"po-mk-{SFX}"
RC_INT, RC_MK, RC_EMPTY = f"rc-int-{SFX}", f"rc-mk-{SFX}", f"rc-empty-{SFX}"
MAT = f"mat-{SFX}"
S = {"je_ids": []}


def _login(email="admin@garment.com", pw="Admin@123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _val(H, as_of=None):
    q = f"?as_of={as_of}" if as_of else ""
    r = requests.get(f"{BASE}/api/rahaza/finance/reports/fg-inventory-valuation{q}", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_00_seed():
    db.production_pos.insert_many([{"id": PO_INT, "po_number": f"PO-INT-{SFX}", "business_type": "internal", "status": "in_production"},
                                   {"id": PO_MK, "po_number": f"PO-MK-{SFX}", "business_type": "maklon", "status": "in_production"}])
    db.rahaza_materials.insert_one({"id": MAT, "code": f"FG-QA-{SFX}", "name": "Kaos QA", "type": "fg"})
    db.cmt_receipts.insert_many([
        {"id": RC_INT, "receipt_code": f"RCV-INT-{SFX}", "po_id": PO_INT, "po_number": f"PO-INT-{SFX}", "cmt_name": "Vendor QA",
         "status": "completed_qc", "qc_completed_at": "2026-08-20T03:00:00+00:00"},
        {"id": RC_MK, "receipt_code": f"RCV-MK-{SFX}", "po_id": PO_MK, "po_number": f"PO-MK-{SFX}", "cmt_name": "Vendor QA",
         "status": "completed_qc", "qc_completed_at": "2026-08-21T03:00:00+00:00"},
        {"id": RC_EMPTY, "receipt_code": f"RCV-EMPTY-{SFX}", "po_id": PO_INT, "po_number": f"PO-INT-{SFX}", "cmt_name": "Vendor QA",
         "status": "approved", "qc_completed_at": "2026-08-22T03:00:00+00:00"},
    ])
    db.fg_cost_layers.insert_many([
        {"id": f"ly1-{SFX}", "material_id": MAT, "sku": f"FG-QA-{SFX}", "qty_in": 10, "qty_remaining": 6, "unit_cost": 20_000.0, "total_cost": 200_000.0,
         "batch": {"po_id": PO_INT, "receipt_id": RC_INT}, "gl_je_id": None},
        {"id": f"ly2-{SFX}", "material_id": MAT, "sku": f"FG-QA-{SFX}", "qty_in": 5, "qty_remaining": 5, "unit_cost": 30_000.0, "total_cost": 150_000.0,
         "batch": {"po_id": PO_INT, "receipt_id": RC_INT}, "gl_je_id": None},
        {"id": f"ly3-{SFX}", "material_id": MAT, "sku": f"FG-QA-{SFX}", "qty_in": 8, "qty_remaining": 8, "unit_cost": 0.0, "total_cost": 0.0,
         "batch": {"po_id": PO_INT, "receipt_id": RC_EMPTY}, "gl_je_id": None},
        {"id": f"ly4-{SFX}", "material_id": f"mat-mk-{SFX}", "sku": "MK", "qty_in": 3, "qty_remaining": 3, "unit_cost": 99_000.0, "total_cost": 297_000.0,
         "batch": {"po_id": PO_MK, "receipt_id": RC_MK}, "gl_je_id": None},
    ])
    db.rahaza_material_stock.insert_one({"id": f"stk-{SFX}", "material_id": MAT, "qty": 20, "quantity": 20, "inventory_category": "fg_internal",
                                         "ownership": "cv_da", "location_id": "qa"})


def test_01_valuation_before_backfill(H):
    d = _val(H)
    row = next(r for r in d["rows"] if r["material_id"] == MAT)
    assert row["code"] == f"FG-QA-{SFX}" and row["name"] == "Kaos QA"
    assert row["stock_qty"] == 20 and row["layer_qty"] == 19 and row["qty_diff"] == 1
    assert row["layer_value"] == 6 * 20_000 + 5 * 30_000 == 270_000
    assert row["uncosted_qty"] == 8 and row["unposted_value"] == 350_000
    assert row["avg_unit_cost"] == round(270_000 / 19, 2)
    t = d["totals"]
    assert t["unposted_layers"] >= 3 and t["unposted_value"] >= 350_000 + 297_000
    # selisih lapisan−GL harus terjelaskan oleh unposted_value bila hanya data uji (unexplained ≈ konstan)
    S["unexplained_before"] = t["unexplained_difference"]
    S["gl_before"] = t["gl_balance"]
    S["gl_before_0819"] = _val(H, "2026-08-19")["totals"]["gl_balance"]


def test_02_backfill_dry_run(H):
    r = requests.post(f"{BASE}/api/prod/cmt-receipts/backfill-wip-fg?dry_run=true", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] is True
    mine = {x["receipt_id"]: x for x in d["rows"] if x["receipt_id"] in (RC_INT, RC_MK, RC_EMPTY)}
    assert mine[RC_INT]["result"] == "candidate" and mine[RC_INT]["value"] == 350_000 and mine[RC_INT]["layers"] == 2
    assert mine[RC_EMPTY]["result"] == "skipped_no_layer_value"
    assert RC_MK not in mine  # maklon dilewati
    assert db.rahaza_journal_entries.count_documents({"source_ref": f"wip_fg_receipt:{RC_INT}"}) == 0


def test_03_backfill_gudang_forbidden():
    g = _login("gudang@dewiaditya.id", "Dewi@123")
    assert requests.post(f"{BASE}/api/prod/cmt-receipts/backfill-wip-fg?dry_run=true", headers=g, timeout=30).status_code == 403


def test_04_backfill_run(H):
    r = requests.post(f"{BASE}/api/prod/cmt-receipts/backfill-wip-fg?dry_run=false", headers=H, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    mine = next(x for x in d["rows"] if x["receipt_id"] == RC_INT)
    assert mine["result"] == "posted" and mine["je_number"], mine
    je = db.rahaza_journal_entries.find_one({"source_ref": f"wip_fg_receipt:{RC_INT}"}, {"_id": 0})
    S["je_ids"].append(je["id"])
    assert je["date"] == "2026-08-20" and je["status"] == "posted"
    ln = {x["account_code"]: x for x in je["lines"]}
    assert ln["1-1404"]["debit"] == 350_000 and ln["1-1403"]["credit"] == 350_000
    assert db.fg_cost_layers.count_documents({"id": {"$in": [f"ly1-{SFX}", f"ly2-{SFX}"]}, "gl_je_id": je["id"]}) == 2
    rc = db.cmt_receipts.find_one({"id": RC_INT}, {"_id": 0})
    assert rc["wip_fg_je_id"] == je["id"] and rc["wip_fg_value"] == 350_000
    # idempoten: run kedua tidak menghasilkan JE baru utk receipt yg sama
    r2 = requests.post(f"{BASE}/api/prod/cmt-receipts/backfill-wip-fg?dry_run=false", headers=H, timeout=120).json()
    assert RC_INT not in [x["receipt_id"] for x in r2["rows"]]
    assert db.rahaza_journal_entries.count_documents({"source_ref": f"wip_fg_receipt:{RC_INT}"}) == 1
    # maklon tidak pernah diposting
    assert db.rahaza_journal_entries.count_documents({"source_ref": f"wip_fg_receipt:{RC_MK}"}) == 0


def test_05_valuation_after_backfill(H):
    d = _val(H)
    row = next(r for r in d["rows"] if r["material_id"] == MAT)
    assert row["unposted_value"] == 0 and row["layer_value"] == 270_000
    t = d["totals"]
    assert t["gl_balance"] == round(S["gl_before"] + 350_000, 2)
    # unexplained tetap (−80.000 = 4 pcs × 20.000 keluar dari lapisan tanpa kredit GL di data uji ini):
    # posting hanya memindahkan nilai dari "unposted" ke "GL"
    assert t["unexplained_difference"] == S["unexplained_before"]
    # as_of sebelum JE → GL tidak memuatnya
    d2 = _val(H, "2026-08-19")
    assert d2["totals"]["gl_balance"] == S["gl_before_0819"]
    assert requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H, timeout=120).json()["balanced"] is True


def test_zz_cleanup():
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": S["je_ids"]}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": S["je_ids"]}})
    db.fg_cost_layers.delete_many({"id": {"$regex": f"-{SFX}$"}})
    db.cmt_receipts.delete_many({"id": {"$in": [RC_INT, RC_MK, RC_EMPTY]}})
    db.production_pos.delete_many({"id": {"$in": [PO_INT, PO_MK]}})
    db.rahaza_materials.delete_one({"id": MAT})
    db.rahaza_material_stock.delete_one({"id": f"stk-{SFX}"})
    assert db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}}) == 0
