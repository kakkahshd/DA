"""
Iter 117 — Portal Penjualan (penjualan langsung FG, tunai/tempo, PPN, FIFO+COGS, AR) · cron overdue (M-07) ·
cron rekonsiliasi FG · cek harga bahan/upah PO internal. Data sintetis, dibersihkan sendiri. Jalankan serial (-n 0).
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
db = MongoClient(os.environ.get("MONGO_URL") or be["MONGO_URL"])[os.environ.get("DB_NAME") or be["DB_NAME"]]
SECRET = be.get("WEBHOOK_CRON_SECRET")
SFX = uuid.uuid4().hex[:6]
MAT_A, MAT_B, LOC = f"mat-a-{SFX}", f"mat-b-{SFX}", f"loc-{SFX}"
S = {}


def _login(email="admin@garment.com", pw="Admin@123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _je_balanced():
    a = list(db.rahaza_journal_lines.aggregate([{"$group": {"_id": None, "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]))
    return not a or round(a[0]["d"], 2) == round(a[0]["c"], 2)


def test_00_seed():
    now = datetime.now(timezone.utc)
    db.rahaza_materials.insert_many([
        {"id": MAT_A, "code": f"FG-A-{SFX}", "name": "Kaos QA A", "type": "fg", "hpp": 40_000, "active": True},
        {"id": MAT_B, "code": f"FG-B-{SFX}", "name": "Kaos QA B", "type": "fg", "hpp": 0, "active": True},
    ])
    db.rahaza_material_stock.insert_many([
        {"id": f"st-a-{SFX}", "material_id": MAT_A, "location_id": LOC, "inventory_category": "fg_internal", "qty": 10, "quantity": 10},
        {"id": f"st-b-{SFX}", "material_id": MAT_B, "location_id": LOC, "inventory_category": "fg_internal", "qty": 5, "quantity": 5},
    ])
    # MAT_A punya lapisan FIFO utk 6 pcs (2 batch); sisanya jatuh ke HPP master
    db.fg_cost_layers.insert_many([
        {"id": f"ly1-{SFX}", "material_id": MAT_A, "sku": f"FG-A-{SFX}", "qty_in": 4, "qty_remaining": 4, "unit_cost": 30_000.0, "total_cost": 120_000.0,
         "breakdown": {"material_cost": 20_000, "sewing_cost": 10_000}, "batch": {"po_number": "PO-QA-1"}, "created_at": now, "gl_je_id": "x"},
        {"id": f"ly2-{SFX}", "material_id": MAT_A, "sku": f"FG-A-{SFX}", "qty_in": 2, "qty_remaining": 2, "unit_cost": 35_000.0, "total_cost": 70_000.0,
         "breakdown": {"material_cost": 25_000, "sewing_cost": 10_000}, "batch": {"po_number": "PO-QA-2"}, "created_at": now, "gl_je_id": "x"},
    ])
    S["kas"] = db.rahaza_cash_accounts.find_one({"active": True}, {"id": 1})
    if not S["kas"]:
        db.rahaza_cash_accounts.insert_one({"id": f"kas-{SFX}", "code": f"KAS-{SFX}", "name": "Kas QA", "type": "cash", "balance": 0, "active": True, "gl_account_code": "1-1201"})
        S["kas"] = {"id": f"kas-{SFX}"}
    S["kas_id"] = S["kas"]["id"]


def test_01_customer_crud(H):
    r = requests.post(f"{BASE}/api/sales/customers", json={"name": f"Pelanggan QA {SFX}", "payment_terms": "net_14", "phone": "0812"}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["code"].startswith("CUST-") and c["payment_terms"] == "net_14"
    S["cust"] = c["id"]
    r = requests.put(f"{BASE}/api/sales/customers/{c['id']}", json={"phone": "0813"}, headers=H, timeout=30)
    assert r.status_code == 200 and r.json()["phone"] == "0813"
    r = requests.post(f"{BASE}/api/sales/customers", json={"name": ""}, headers=H, timeout=30)
    assert r.status_code == 400


def test_02_fg_stock_list(H):
    r = requests.get(f"{BASE}/api/sales/fg-stock", headers=H, timeout=30)
    assert r.status_code == 200
    row = next(x for x in r.json() if x["material_id"] == MAT_A)
    assert row["available_qty"] == 10 and row["sku"] == f"FG-A-{SFX}"


def test_03_validation(H):
    body = {"customer_id": S["cust"], "payment_type": "cash", "cash_account_id": S["kas_id"], "items": [{"material_id": MAT_A, "qty": 99, "price": 1000}]}
    r = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30)
    assert r.status_code == 400 and "Stok" in r.json()["detail"]
    body["items"][0]["qty"] = 1
    body.pop("cash_account_id")
    r = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30)
    assert r.status_code == 400 and "Rekening" in r.json()["detail"]
    r = requests.post(f"{BASE}/api/sales/direct-sales", json={**body, "customer_id": "nope", "cash_account_id": S["kas_id"]}, headers=H, timeout=30)
    assert r.status_code == 400


def test_04_cash_sale_ppn(H):
    body = {"customer_id": S["cust"], "payment_type": "cash", "cash_account_id": S["kas_id"], "tax_pct": 11,
            "items": [{"material_id": MAT_A, "qty": 7, "price": 100_000}]}
    r = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["status"] == "draft" and n["subtotal"] == 700_000 and n["tax_amount"] == 77_000 and n["total"] == 777_000
    S["n1"] = n["id"]
    kas_before = db.rahaza_cash_accounts.find_one({"id": S["kas_id"]})["balance"]
    r = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/confirm", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid" and d["invoice_number"] and d["ar_je_id"] and d["payment_je_id"]
    # FIFO: 4×30k + 2×35k = 190k; 1 pcs tanpa lapisan → HPP master (sudah diperbarui ke batch terakhir oleh FIFO) ⇒ mixed
    hpp_now = db.rahaza_materials.find_one({"id": MAT_A})["hpp"]
    assert d["cogs_basis"] == "mixed" and d["uncosted_qty"] == 1 and d["cogs_estimated"] == hpp_now * 1
    assert d["cogs_total"] == 190_000 + d["cogs_estimated"]
    assert d["cogs_je_id"]
    stock = sum(s["qty"] for s in db.rahaza_material_stock.find({"material_id": MAT_A}))
    assert stock == 3
    assert sum(l["qty_remaining"] for l in db.fg_cost_layers.find({"material_id": MAT_A})) == 0
    inv = db.rahaza_ar_invoices.find_one({"id": d["ar_invoice_id"]})
    assert inv["status"] == "paid" and inv["balance"] == 0 and inv["source_module"] == "direct_sale" and inv["gl_je_id"]
    assert db.rahaza_cash_accounts.find_one({"id": S["kas_id"]})["balance"] == kas_before + 777_000
    je = db.rahaza_journal_entries.find_one({"id": d["cogs_je_id"]})
    assert je["total_debit"] == d["cogs_total"] and any(l["account_code"] == "1-1404" and l["credit"] == d["cogs_total"] for l in je["lines"])
    assert _je_balanced()
    # konfirmasi ulang ditolak
    assert requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/confirm", headers=H, timeout=30).status_code == 400


def test_05_credit_sale_payment_overdue(H):
    body = {"customer_id": S["cust"], "payment_type": "credit", "due_date": "2026-01-15", "discount_amount": 5_000,
            "items": [{"material_id": MAT_B, "qty": 2, "price": 50_000}]}
    r = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["due_date"] == "2026-01-15" and n["total"] == 95_000
    S["n2"] = n["id"]
    r = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/confirm", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "confirmed" and d["cogs_je_id"] is None and d["cogs_post_error"]  # MAT_B: tanpa lapisan & hpp 0 → jujur 0
    assert d["uncosted_qty"] == 2
    inv = db.rahaza_ar_invoices.find_one({"id": d["ar_invoice_id"]})
    assert inv["status"] == "issued" and inv["balance"] == 95_000
    # cron overdue: webhook tanpa/dgn secret, idempoten per X-Webhook-Id
    assert requests.post(f"{BASE}/api/cron/mark-overdue", json={}, timeout=30).status_code == 401
    assert requests.post(f"{BASE}/api/cron/mark-overdue", json={}, headers={"Authorization": "Bearer salah"}, timeout=30).status_code == 401
    rid = f"qa-{SFX}"
    hh = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": rid}
    assert requests.post(f"{BASE}/api/cron/mark-overdue", json={"event": "schedule.triggered", "run_id": rid}, headers=hh, timeout=30).json()["status"] == "accepted"
    assert requests.post(f"{BASE}/api/cron/mark-overdue", json={}, headers=hh, timeout=30).json()["status"] == "duplicate"
    import time
    for _ in range(20):
        run = db.cron_runs.find_one({"run_id": rid})
        if run and run["status"] != "running":
            break
        time.sleep(0.5)
    assert run["status"] == "ok", run
    assert db.rahaza_ar_invoices.find_one({"id": d["ar_invoice_id"]})["status"] == "overdue"
    ag = requests.get(f"{BASE}/api/rahaza/ar-aging", headers=H, timeout=30).json()
    assert any(x.get("id") == d["ar_invoice_id"] and x["status"] == "overdue" for x in ag["details"])
    # bayar parsial lalu lunas
    r = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/payment", json={"amount": 45_000, "cash_account_id": S["kas_id"]}, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["invoice"]["status"] == "partial_paid" and r.json()["invoice"]["balance"] == 50_000
    r = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/payment", json={"amount": 60_000, "cash_account_id": S["kas_id"]}, headers=H, timeout=60)
    assert r.status_code == 400
    r = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/payment", json={"amount": 50_000, "cash_account_id": S["kas_id"]}, headers=H, timeout=60)
    assert r.status_code == 200 and r.json()["note"]["status"] == "paid"
    assert _je_balanced()


def test_06_cancel_draft_only(H):
    body = {"customer_id": S["cust"], "payment_type": "credit", "items": [{"material_id": MAT_A, "qty": 1, "price": 10_000}]}
    n = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30).json()
    S["n3"] = n["id"]
    assert n["due_date"] > n["sale_date"]  # termin net_14 pelanggan
    assert requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/cancel", headers=H, timeout=30).json()["status"] == "cancelled"
    assert requests.post(f"{BASE}/api/sales/direct-sales/{S['n1']}/cancel", headers=H, timeout=30).status_code == 400


def test_07_list_detail_pdf_dashboard(H):
    rows = requests.get(f"{BASE}/api/sales/direct-sales", headers=H, timeout=30).json()
    assert any(r["id"] == S["n1"] and r["ar_status"] == "paid" for r in rows)
    d = requests.get(f"{BASE}/api/sales/direct-sales/{S['n2']}", headers=H, timeout=30).json()
    assert d["invoice"]["status"] == "paid" and len(d["payments"]) == 2
    r = requests.get(f"{BASE}/api/sales/direct-sales/{S['n1']}/pdf", headers=H, timeout=60)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content[:4] == b"%PDF"
    dash = requests.get(f"{BASE}/api/sales/dashboard", headers=H, timeout=30).json()
    assert dash["month_sales"] >= 872_000 and any(s["sku"] == f"FG-A-{SFX}" for s in dash["top_skus"])


def test_08_rbac(H):
    h = _login("gudang@dewiaditya.id", "Dewi@123")  # admin_gudang boleh masuk portal
    assert requests.get(f"{BASE}/api/sales/fg-stock", headers=h, timeout=30).status_code == 200
    h = _login("hr@dewiaditya.id", "Dewi@123")
    assert requests.get(f"{BASE}/api/sales/fg-stock", headers=h, timeout=30).status_code == 403
    assert requests.get(f"{BASE}/api/cron/runs", headers=h, timeout=30).status_code == 403


def test_09_fg_valuation_cron(H):
    r = requests.post(f"{BASE}/api/cron/fg-valuation-check/run-now", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert {"difference", "unexplained_difference", "explained", "notified"} <= set(res)
    if not res["explained"]:
        assert db.notifications.find_one({"source_ref": f"fgval:{res['date']}", "subtype": "fg_valuation_unexplained"})
    runs = requests.get(f"{BASE}/api/cron/runs?job=fg-valuation-check", headers=H, timeout=30).json()
    assert runs and runs[0]["status"] == "ok"


def test_10_po_cost_check(H):
    po = db.production_pos.find_one({"business_type": "internal"}) or db.production_pos.find_one({})
    r = requests.get(f"{BASE}/api/production-pos/{po['id']}/cost-check", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "items_with_issues" in d and isinstance(d["items"], list)
    for it in d["items"]:
        if it["sewing_cost"] <= 0:
            assert any("upah" in x for x in it["issues"])
    assert requests.get(f"{BASE}/api/production-pos/nope-{SFX}/cost-check", headers=H, timeout=30).status_code == 404


def test_99_cleanup():
    note_ids = [S.get(k) for k in ("n1", "n2", "n3") if S.get(k)]
    invs = list(db.rahaza_ar_invoices.find({"direct_sale_id": {"$in": note_ids}}, {"id": 1}))
    inv_ids = [i["id"] for i in invs]
    mv = list(db.rahaza_cash_movements.find({"ref_id": {"$in": inv_ids}}))
    mv_ids = [m["id"] for m in mv]
    je_ids = [j["id"] for j in db.rahaza_journal_entries.find({"$or": [
        {"source_ref": {"$in": [f"ar:{i}" for i in inv_ids] + [f"cogs_sale:{n}" for n in note_ids]}},
        {"source_module": "ar_payment", "source_ref": {"$regex": "|".join(mv_ids) if mv_ids else "^$"}},
    ]}, {"id": 1})]
    for m in mv:
        db.rahaza_cash_accounts.update_one({"id": m["account_id"]}, {"$inc": {"balance": -m["amount"]}})
    db.rahaza_cash_movements.delete_many({"ref_id": {"$in": inv_ids}})
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": je_ids}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": je_ids}})
    db.rahaza_ar_invoices.delete_many({"id": {"$in": inv_ids}})
    db.sales_direct_notes.delete_many({"id": {"$in": note_ids}})
    db.fg_cost_consumptions.delete_many({"material_id": {"$in": [MAT_A, MAT_B]}})
    db.fg_cost_layers.delete_many({"material_id": {"$in": [MAT_A, MAT_B]}})
    db.rahaza_material_stock.delete_many({"material_id": {"$in": [MAT_A, MAT_B]}})
    db.rahaza_stock_ledger.delete_many({"material_id": {"$in": [MAT_A, MAT_B]}})
    db.rahaza_fg_movements.delete_many({"material_id": {"$in": [MAT_A, MAT_B]}})
    db.rahaza_materials.delete_many({"id": {"$in": [MAT_A, MAT_B]}})
    if S.get("cust"):
        c = db.rahaza_customers.find_one({"id": S["cust"]})
        db.rahaza_coa_accounts.delete_many({"code": (c or {}).get("ar_account_code", "__none__")})
        db.rahaza_customers.delete_one({"id": S["cust"]})
    db.cron_runs.delete_many({"run_id": {"$regex": f"qa-{SFX}"}})
    db.rahaza_cash_accounts.delete_many({"id": f"kas-{SFX}"})
    assert _je_balanced()
