"""
Iter 115 — PO INTERNAL = produksi stok sendiri (keputusan bisnis owner):
  1. "Serah Terima FG" (buyer_shipment receiver=buyer) utk PO internal: dokumen tercatat, TAPI stok FG tidak berkurang,
     tidak ada rahaza_fg_movements OUT, tidak ada JE cogs_shipment, tidak ada AR/pendapatan (H-07 dicabut);
     response: fg_stock.skipped == 'internal_handover', cogs_posting.skipped == 'internal_handover', handover_mode tersimpan.
  2. post_wip_to_fg_on_cmt_receipt: Terima FG dari CMT PO internal → JE Dr 1-1404 / Cr 1-1403 = Σ total_cost lapisan
     receipt; idempoten; lapisan ditandai gl_je_id; post_wip_to_fg_on_job_complete mengabaikan lapisan yang sudah ber-gl_je_id.
  3. Endpoint H-07 (/api/buyer-shipments/{id}/post-revenue) sudah tidak ada → 404/405.
Data uji sintetis, dibersihkan sendiri.
"""
import asyncio
import os
import sys
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
db = MongoClient(os.environ.get("MONGO_URL") or be["MONGO_URL"])[os.environ.get("DB_NAME") or be["DB_NAME"]]
SFX = uuid.uuid4().hex[:6]
RCPT = f"rcpt-qa-{SFX}"
S = {"je_ids": [], "layer_ids": []}


def _login(email="admin@garment.com", pw="Admin@123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _run(coro_fn):
    from motor.motor_asyncio import AsyncIOMotorClient

    async def go():
        adb = AsyncIOMotorClient(be["MONGO_URL"])[be["DB_NAME"]]
        return await coro_fn(adb)
    return asyncio.run(go())


def test_01_internal_dispatch_is_handover_only(H):
    """Pakai PO internal demo (seed) bila ada hasil produksi; kalau tidak ada, buat sintetis lewat Mongo & endpoint."""
    po = db.production_pos.find_one({"business_type": "internal", "status": {"$nin": ["Cancelled", "Closed", "closed"]}}, {"_id": 0})
    if not po:
        pytest.skip("tidak ada PO internal aktif di seed")
    pi = db.po_items.find_one({"po_id": po["id"]}, {"_id": 0})
    assert pi, "PO internal tanpa po_items"
    # pastikan ada hasil produksi utk pagar kapasitas: naikkan produced_qty job item sintetis bila perlu
    ji = db.production_job_items.find_one({"po_item_id": pi["id"]}, {"_id": 0})
    if not ji:
        db.production_job_items.insert_one({"id": f"ji-qa-{SFX}", "po_item_id": pi["id"], "po_id": po["id"], "job_id": f"job-qa-{SFX}",
                                            "sku": pi.get("sku"), "produced_qty": 5, "available_qty": 5, "received_qty": 5})
        S["ji_qa"] = f"ji-qa-{SFX}"
    elif int(ji.get("produced_qty") or 0) <= 0:
        db.production_job_items.update_one({"id": ji["id"]}, {"$set": {"produced_qty": 5, "available_qty": 5}})
        S["ji_restore"] = (ji["id"], ji.get("produced_qty"), ji.get("available_qty"))
    before_stock = list(db.rahaza_material_stock.find({"inventory_category": "fg_internal"}, {"_id": 0, "id": 1, "quantity": 1, "qty": 1}))
    before_mv = db.rahaza_fg_movements.count_documents({"source": "buyer_shipment"})
    before_je = db.rahaza_journal_entries.count_documents({})
    body = {"po_id": po["id"], "receiver_type": "buyer", "shipment_date": "2026-09-01",
            "items": [{"po_item_id": pi["id"], "sku": pi.get("sku"), "qty_shipped": 1}]}
    r = requests.post(f"{BASE}/api/buyer-shipments", headers=H, json=body, timeout=60)
    assert r.status_code in (200, 201), r.text
    d = r.json()
    S["shp_id"] = d["id"]
    assert d["fg_stock"]["skipped"] == "internal_handover", d["fg_stock"]
    assert d["cogs_posting"]["skipped"] == "internal_handover"
    assert "revenue_posting" not in d
    assert db.buyer_shipments.find_one({"id": d["id"]})["handover_mode"] == "warehouse_handover"
    assert db.buyer_shipment_items.count_documents({"shipment_id": d["id"], "fg_issued_at": {"$ne": None}}) == 0
    assert db.rahaza_fg_movements.count_documents({"source": "buyer_shipment"}) == before_mv
    assert db.rahaza_journal_entries.count_documents({}) == before_je
    assert db.rahaza_ar_invoices.count_documents({"linked_shipment_id": d["id"]}) == 0
    after_stock = list(db.rahaza_material_stock.find({"inventory_category": "fg_internal"}, {"_id": 0, "id": 1, "quantity": 1, "qty": 1}))
    assert after_stock == before_stock


def test_02_h07_endpoint_removed(H):
    r = requests.post(f"{BASE}/api/buyer-shipments/xyz/post-revenue", headers=H, timeout=30)
    assert r.status_code in (404, 405), r.status_code


def test_03_wip_to_fg_on_cmt_receipt_internal():
    db.fg_cost_layers.insert_many([
        {"id": f"ly1-{SFX}", "material_id": f"mat-qa-{SFX}", "qty": 10, "unit_cost": 25_000.0, "total_cost": 250_000.0,
         "batch": {"po_id": f"po-qa-{SFX}", "receipt_id": RCPT}, "gl_je_id": None, "gl_job_id": None, "remaining_qty": 10},
        {"id": f"ly2-{SFX}", "material_id": f"mat-qa-{SFX}", "qty": 4, "unit_cost": 30_000.0, "total_cost": 120_000.0,
         "batch": {"po_id": f"po-qa-{SFX}", "receipt_id": RCPT}, "gl_je_id": None, "gl_job_id": None, "remaining_qty": 4},
    ])
    S["layer_ids"] = [f"ly1-{SFX}", f"ly2-{SFX}"]
    db.cmt_receipts.insert_one({"id": RCPT, "receipt_code": f"RCV-QA-{SFX}", "po_id": f"po-qa-{SFX}", "po_number": f"PO-QA-{SFX}",
                                "cmt_name": "Vendor QA", "status": "Approved", "qc_completed_at": "2026-08-28T05:00:00+00:00"})
    from routes.rahaza_posting import post_wip_to_fg_on_cmt_receipt, post_wip_to_fg_on_job_complete

    async def go(adb):
        rc = await adb.cmt_receipts.find_one({"id": RCPT}, {"_id": 0})
        r1 = await post_wip_to_fg_on_cmt_receipt(adb, rc, S["layer_ids"], {"id": "qa", "name": "QA"})
        r2 = await post_wip_to_fg_on_cmt_receipt(adb, rc, S["layer_ids"], {"id": "qa", "name": "QA"})
        # job complete utk PO yang sama TIDAK boleh mengulang lapisan yang sudah dibukukan
        job = {"id": f"job-qa-{SFX}", "job_number": f"JOB-QA-{SFX}", "po_id": f"po-qa-{SFX}", "completed_at": "2026-08-29"}
        r3 = await post_wip_to_fg_on_job_complete(adb, job, {"id": "qa", "name": "QA"})
        return r1, r2, r3
    r1, r2, r3 = _run(go)
    assert r1["ok"], r1
    S["je_ids"].append(r1["je_id"])
    je = db.rahaza_journal_entries.find_one({"id": r1["je_id"]}, {"_id": 0})
    assert je["date"] == "2026-08-28" and je["source_module"] == "cmt_receipt" and je["source_ref"] == f"wip_fg_receipt:{RCPT}"
    ln = {x["account_code"]: x for x in je["lines"]}
    assert ln["1-1404"]["debit"] == 370_000 and ln["1-1403"]["credit"] == 370_000
    assert r2["already_posted"] and r2["je_id"] == r1["je_id"]
    assert db.fg_cost_layers.count_documents({"id": {"$in": S["layer_ids"]}, "gl_je_id": r1["je_id"]}) == 2
    rc = db.cmt_receipts.find_one({"id": RCPT}, {"_id": 0})
    assert rc["wip_fg_je_id"] == r1["je_id"] and rc["wip_fg_value"] == 370_000
    assert r3.get("ok") is False and r3.get("reason") == "zero_wip_value", r3
    assert db.rahaza_journal_entries.count_documents({"source_ref": f"wip_fg_job:job-qa-{SFX}"}) == 0
    db.production_jobs.delete_many({"id": f"job-qa-{SFX}"})


def test_04_balance_sheet_ok(H):
    r = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H, timeout=120)
    assert r.status_code == 200 and r.json()["balanced"] is True


def test_zz_cleanup():
    if S.get("shp_id"):
        db.buyer_shipment_items.delete_many({"shipment_id": S["shp_id"]})
        db.buyer_shipments.delete_one({"id": S["shp_id"]})
    if S.get("ji_qa"):
        db.production_job_items.delete_one({"id": S["ji_qa"]})
    if S.get("ji_restore"):
        jid, pq, aq = S["ji_restore"]
        db.production_job_items.update_one({"id": jid}, {"$set": {"produced_qty": pq, "available_qty": aq}})
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": S["je_ids"]}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": S["je_ids"]}})
    db.fg_cost_layers.delete_many({"id": {"$in": S["layer_ids"]}})
    db.cmt_receipts.delete_one({"id": RCPT})
    db.production_jobs.delete_many({"id": f"job-qa-{SFX}"})
    assert db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}}) == 0
