"""
Iter 115 supplemental QA — reviewer-driven scenarios:
  A. Second dispatch (seq 2) to same SJ still handover-only.
  B. Maklon regression: POST /api/buyer-shipments untuk PO maklon tanpa source_receipt_ids → 400 memuat 'source_receipt_ids'.
  C. H-07 removed: GET/POST post-revenue & GET revenue → 404/405.
  D. Alerts + year-end preview + balance-sheet.
  E. journal_lines orphan check.
Auto-cleanup semua data uji.
"""
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
S = {"shp_ids": [], "ji_qa": None, "ji_restore": None}


def _login(email="admin@garment.com", pw="Admin@123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _ensure_internal_po_ready():
    po = db.production_pos.find_one({"business_type": "internal", "status": {"$nin": ["Cancelled", "Closed", "closed"]}}, {"_id": 0})
    if not po:
        pytest.skip("no active internal PO in seed")
    pi = db.po_items.find_one({"po_id": po["id"]}, {"_id": 0})
    assert pi, "internal PO has no items"
    ji = db.production_job_items.find_one({"po_item_id": pi["id"]}, {"_id": 0})
    if not ji:
        db.production_job_items.insert_one({"id": f"ji-qa-{SFX}", "po_item_id": pi["id"], "po_id": po["id"],
                                            "job_id": f"job-qa-{SFX}", "sku": pi.get("sku"),
                                            "produced_qty": 5, "available_qty": 5, "received_qty": 5})
        S["ji_qa"] = f"ji-qa-{SFX}"
    elif int(ji.get("produced_qty") or 0) <= 0:
        db.production_job_items.update_one({"id": ji["id"]}, {"$set": {"produced_qty": 5, "available_qty": 5}})
        S["ji_restore"] = (ji["id"], ji.get("produced_qty"), ji.get("available_qty"))
    return po, pi


def test_A_double_dispatch_same_po_still_handover(H):
    po, pi = _ensure_internal_po_ready()
    before_stock = list(db.rahaza_material_stock.find({"inventory_category": "fg_internal"}, {"_id": 0, "id": 1, "quantity": 1}))
    before_mv = db.rahaza_fg_movements.count_documents({"source": "buyer_shipment"})
    before_je = db.rahaza_journal_entries.count_documents({})
    body = {"po_id": po["id"], "receiver_type": "buyer", "shipment_date": "2026-09-01",
            "items": [{"po_item_id": pi["id"], "sku": pi.get("sku"), "qty_shipped": 1}]}
    r1 = requests.post(f"{BASE}/api/buyer-shipments", headers=H, json=body, timeout=60)
    assert r1.status_code in (200, 201), r1.text
    d1 = r1.json()
    S["shp_ids"].append(d1["id"])
    assert d1["fg_stock"]["skipped"] == "internal_handover"
    assert d1["cogs_posting"]["skipped"] == "internal_handover"
    assert "revenue_posting" not in d1

    # second dispatch
    r2 = requests.post(f"{BASE}/api/buyer-shipments", headers=H, json=body, timeout=60)
    assert r2.status_code in (200, 201), r2.text
    d2 = r2.json()
    S["shp_ids"].append(d2["id"])
    assert d2["fg_stock"]["skipped"] == "internal_handover"
    assert d2["cogs_posting"]["skipped"] == "internal_handover"
    assert "revenue_posting" not in d2

    # invariants
    assert db.rahaza_fg_movements.count_documents({"source": "buyer_shipment"}) == before_mv
    assert db.rahaza_journal_entries.count_documents({}) == before_je
    after_stock = list(db.rahaza_material_stock.find({"inventory_category": "fg_internal"}, {"_id": 0, "id": 1, "quantity": 1}))
    assert after_stock == before_stock

    # GET returns items
    g = requests.get(f"{BASE}/api/buyer-shipments/{d1['id']}", headers=H, timeout=30)
    assert g.status_code == 200
    gj = g.json()
    assert gj.get("items"), "GET buyer-shipment items missing"


def test_B_maklon_regression_requires_source_receipts(H):
    po_m = db.production_pos.find_one({"business_type": "maklon", "status": {"$nin": ["Cancelled", "Closed", "closed"]}}, {"_id": 0})
    if not po_m:
        pytest.skip("no active maklon PO in seed")
    pim = db.po_items.find_one({"po_id": po_m["id"]}, {"_id": 0})
    if not pim:
        pytest.skip("maklon PO has no items")
    body = {"po_id": po_m["id"], "receiver_type": "buyer", "shipment_date": "2026-09-01",
            "items": [{"po_item_id": pim["id"], "sku": pim.get("sku"), "qty_shipped": 1}]}
    r = requests.post(f"{BASE}/api/buyer-shipments", headers=H, json=body, timeout=60)
    assert r.status_code == 400, f"expected 400 for maklon w/o source_receipt_ids; got {r.status_code}: {r.text}"
    assert "source_receipt_ids" in r.text, r.text


def test_C_h07_removed_variants(H):
    r_post = requests.post(f"{BASE}/api/buyer-shipments/anyid/post-revenue", headers=H, timeout=30)
    assert r_post.status_code in (404, 405), r_post.status_code
    r_get = requests.get(f"{BASE}/api/buyer-shipments/anyid/revenue", headers=H, timeout=30)
    assert r_get.status_code in (404, 405), r_get.status_code


def test_D_alerts_and_year_end(H):
    r1 = requests.get(f"{BASE}/api/rahaza/periods/alerts", headers=H, timeout=60)
    assert r1.status_code == 200, r1.text
    r2 = requests.get(f"{BASE}/api/rahaza/year-end/preview?year=2026", headers=H, timeout=60)
    assert r2.status_code == 200, r2.text
    r3 = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H, timeout=120)
    assert r3.status_code == 200 and r3.json()["balanced"] is True
    assert r3.json().get("orphan_account_lines") in (None, [], 0)


def test_E_no_orphan_journal_lines():
    orphan = db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}})
    assert orphan == 0, f"orphan journal_lines={orphan}"


def test_zz_cleanup():
    for sid in S["shp_ids"]:
        db.buyer_shipment_items.delete_many({"shipment_id": sid})
        db.buyer_shipments.delete_one({"id": sid})
    if S.get("ji_qa"):
        db.production_job_items.delete_one({"id": S["ji_qa"]})
    if S.get("ji_restore"):
        jid, pq, aq = S["ji_restore"]
        db.production_job_items.update_one({"id": jid}, {"$set": {"produced_qty": pq, "available_qty": aq}})
