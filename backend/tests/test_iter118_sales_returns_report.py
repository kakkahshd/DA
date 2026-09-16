"""
Iter 118 — Retur penjualan langsung (nota kredit + stok kembali + balik HPP + refund), laporan penjualan (CSV),
template nota PDF (doc_key sales-note), PPN dihitung setelah diskon & AR posting dengan diskon. Serial (-n 0).
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
SFX = uuid.uuid4().hex[:6]
MAT, LOC = f"mat-r-{SFX}", f"loc-r-{SFX}"
S = {}


@pytest.fixture(scope="module")
def H():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@garment.com", "password": "Admin@123"}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


def _bal():
    a = list(db.rahaza_journal_lines.aggregate([{"$group": {"_id": None, "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]))
    return not a or round(a[0]["d"], 2) == round(a[0]["c"], 2)


def _stock():
    return sum(s["qty"] for s in db.rahaza_material_stock.find({"material_id": MAT}))


def test_00_seed(H):
    now = datetime.now(timezone.utc)
    db.rahaza_materials.insert_one({"id": MAT, "code": f"FG-R-{SFX}", "name": "Kaos Retur QA", "type": "fg", "hpp": 0, "active": True})
    db.rahaza_material_stock.insert_one({"id": f"st-r-{SFX}", "material_id": MAT, "location_id": LOC, "inventory_category": "fg_internal", "qty": 10, "quantity": 10})
    db.fg_cost_layers.insert_one({"id": f"ly-r-{SFX}", "material_id": MAT, "sku": f"FG-R-{SFX}", "qty_in": 10, "qty_remaining": 10, "unit_cost": 40_000.0, "total_cost": 400_000.0,
                                  "breakdown": {"material_cost": 30_000, "sewing_cost": 10_000}, "batch": {"po_number": "PO-QA-R"}, "created_at": now, "gl_je_id": "x"})
    kas = db.rahaza_cash_accounts.find_one({"active": True}, {"id": 1})
    S["kas"] = kas["id"]
    c = requests.post(f"{BASE}/api/sales/customers", json={"name": f"Pelanggan Retur {SFX}", "payment_terms": "net_30"}, headers=H, timeout=30).json()
    S["cust"] = c["id"]


def test_01_discount_tax_after_discount_and_ar_posted(H):
    body = {"customer_id": S["cust"], "payment_type": "cash", "cash_account_id": S["kas"], "tax_pct": 11, "discount_amount": 20_000,
            "items": [{"material_id": MAT, "qty": 4, "price": 100_000}]}
    n = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30).json()
    assert n["subtotal"] == 400_000 and n["tax_amount"] == 41_800 and n["total"] == 421_800  # PPN atas 380.000
    d = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/confirm", headers=H, timeout=60).json()
    S["n1"] = n["id"]
    assert d["status"] == "paid" and d["ar_je_id"] and not d.get("ar_post_error"), d
    je = db.rahaza_journal_entries.find_one({"id": d["ar_je_id"]})
    codes = {l["account_code"]: (l["debit"], l["credit"]) for l in je["lines"]}
    assert codes["4-1300"] == (20_000, 0) and codes["4-1100"] == (0, 400_000) and codes["2-1400"] == (0, 41_800)
    inv = db.rahaza_ar_invoices.find_one({"id": d["ar_invoice_id"]})
    assert inv["subtotal"] == 380_000 and inv["total"] == 421_800 and inv["gl_ar_account_code"].startswith("1-1301")
    assert d["cogs_total"] == 160_000 and d["cogs_basis"] == "fifo_batch"
    assert _stock() == 6 and _bal()


def test_02_return_paid_note_cash_refund(H):
    r = requests.post(f"{BASE}/api/sales/direct-sales/{S['n1']}/returns", headers=H, timeout=60,
                      json={"items": [{"material_id": MAT, "qty": 1}], "reason": "Cacat jahitan", "refund_method": "cash", "cash_account_id": S["kas"]})
    assert r.status_code == 200, r.text
    d = r.json()
    S["ret1"] = d["id"]
    # 1 pcs × 100.000 × faktor diskon 0,95 = 95.000 + PPN 10.450 = 105.450
    assert d["subtotal"] == 95_000 and d["tax_amount"] == 10_450 and d["total"] == 105_450
    assert d["cogs_total"] == 40_000 and d["cn_number"].startswith("CN-") and d["cn_je_id"] and d["cogs_je_id"]
    assert d["applied_to_invoice"] == 0 and d["refund_amount"] == 105_450 and d["refund_je_id"]
    assert _stock() == 7
    lay = db.fg_cost_layers.find_one({"material_id": MAT, "batch.source": "sales_return"})
    assert lay and lay["qty_remaining"] == 1 and lay["unit_cost"] == 40_000
    cn = db.rahaza_journal_entries.find_one({"id": d["cn_je_id"]})
    codes = {l["account_code"]: (l["debit"], l["credit"]) for l in cn["lines"]}
    inv = db.rahaza_ar_invoices.find_one({"direct_sale_id": S["n1"]})
    assert codes["4-1200"] == (95_000, 0) and codes["2-1400"] == (10_450, 0) and codes[inv["gl_ar_account_code"]] == (0, 105_450)
    assert inv["credited_amount"] == 105_450 and inv["status"] == "paid"
    cg = db.rahaza_journal_entries.find_one({"id": d["cogs_je_id"]})
    assert any(l["account_code"] == "1-1404" and l["debit"] == 40_000 for l in cg["lines"])
    assert db.rahaza_cash_movements.find_one({"id": d["refund_movement_id"], "direction": "out", "amount": 105_450})
    assert _bal()
    # retur melebihi sisa ditolak; nota draft tidak bisa diretur
    r = requests.post(f"{BASE}/api/sales/direct-sales/{S['n1']}/returns", headers=H, timeout=30, json={"items": [{"material_id": MAT, "qty": 4}]})
    assert r.status_code == 400 and "maksimal retur 3" in r.json()["detail"]


def test_03_return_credit_note_applies_to_open_invoice(H):
    body = {"customer_id": S["cust"], "payment_type": "credit", "items": [{"material_id": MAT, "qty": 2, "price": 50_000}]}
    n = requests.post(f"{BASE}/api/sales/direct-sales", json=body, headers=H, timeout=30).json()
    S["n2"] = n["id"]
    requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/confirm", headers=H, timeout=60)
    d = requests.post(f"{BASE}/api/sales/direct-sales/{n['id']}/returns", headers=H, timeout=60,
                      json={"items": [{"material_id": MAT, "qty": 1, "condition": "damaged"}], "reason": "rusak"}).json()
    S["ret2"] = d["id"]
    assert d["total"] == 50_000 and d["applied_to_invoice"] == 50_000 and d["refund_amount"] == 0 and not d.get("customer_credit")
    inv = db.rahaza_ar_invoices.find_one({"id": n["ar_invoice_id"]}) if n.get("ar_invoice_id") else db.rahaza_ar_invoices.find_one({"direct_sale_id": n["id"]})
    assert inv["balance"] == 50_000 and inv["status"] == "issued"
    assert _stock() == 5  # rusak → tidak kembali ke stok
    assert _bal()


def test_04_detail_list_report(H):
    det = requests.get(f"{BASE}/api/sales/direct-sales/{S['n1']}", headers=H, timeout=30).json()
    assert len(det["returns"]) == 1 and det["returned_total"] == 105_450 and det["returned_qty"] == 1
    rows = requests.get(f"{BASE}/api/sales/returns?direct_sale_id={S['n1']}", headers=H, timeout=30).json()
    assert len(rows) == 1
    rep = requests.get(f"{BASE}/api/sales/report?group_by=customer", headers=H, timeout=30).json()
    row = next(r for r in rep["rows"] if r["key"] == S["cust"])
    # bruto 500.000, diskon 20.000, retur 95.000 + 50.000, bersih 335.000; HPP 160k+80k−40k−40k = 160k
    assert row["notes"] == 2 and row["qty"] == 6 and row["gross"] == 500_000 and row["discount"] == 20_000
    assert row["returns"] == 145_000 and row["net_sales"] == 335_000 and row["cogs"] == 160_000 and row["margin"] == 175_000
    for g in ("sku", "day", "month"):
        assert requests.get(f"{BASE}/api/sales/report?group_by={g}", headers=H, timeout=30).status_code == 200
    csv = requests.get(f"{BASE}/api/sales/report?group_by=customer&format=csv", headers=H, timeout=30)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and "Penjualan Bersih" in csv.text and "TOTAL" in csv.text
    assert requests.get(f"{BASE}/api/sales/report?group_by=xx", headers=H, timeout=30).status_code == 400


def test_05_pdf_uses_template(H):
    cat = requests.get(f"{BASE}/api/pdf-templates/catalog", headers=H, timeout=30).json()
    items = cat if isinstance(cat, list) else (cat.get("items") or cat.get("catalog") or cat.get("docs"))
    sn = next(x for x in items if x["doc_key"] == "sales-note")
    assert sn["title"] == "NOTA PENJUALAN" and any(c["key"] == "sku" for c in sn["columns"])
    r = requests.get(f"{BASE}/api/sales/direct-sales/{S['n1']}/pdf", headers=H, timeout=60)
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 1500
    r = requests.get(f"{BASE}/api/pdf-templates/sales-note/preview", headers=H, timeout=60)
    assert r.status_code in (200, 404)


def test_99_cleanup():
    note_ids = [S.get(k) for k in ("n1", "n2") if S.get(k)]
    invs = [i["id"] for i in db.rahaza_ar_invoices.find({"direct_sale_id": {"$in": note_ids}}, {"id": 1})]
    rets = [r["id"] for r in db.sales_direct_returns.find({"direct_sale_id": {"$in": note_ids}}, {"id": 1})]
    cns = [c["id"] for c in db.rahaza_credit_notes.find({"direct_sale_id": {"$in": note_ids}}, {"id": 1})]
    movs = list(db.rahaza_cash_movements.find({"ref_id": {"$in": invs}}))
    for m in movs:
        db.rahaza_cash_accounts.update_one({"id": m["account_id"]}, {"$inc": {"balance": (-m["amount"] if m["direction"] == "in" else m["amount"])}})
    refs = [f"ar:{i}" for i in invs] + [f"cogs_sale:{n}" for n in note_ids] + [f"cn:{c}" for c in cns] + [f"refund:{r}" for r in rets] + [f"cogs_return:{r}" for r in rets]
    mv_ids = [m["id"] for m in movs]
    je_ids = [j["id"] for j in db.rahaza_journal_entries.find({"$or": [{"source_ref": {"$in": refs}},
                                                                      {"source_module": "ar_payment", "source_ref": {"$regex": "|".join(mv_ids) or "^$"}}]}, {"id": 1})]
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": je_ids}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": je_ids}})
    db.rahaza_cash_movements.delete_many({"ref_id": {"$in": invs}})
    db.rahaza_ar_invoices.delete_many({"id": {"$in": invs}})
    db.rahaza_credit_notes.delete_many({"id": {"$in": cns}})
    db.sales_direct_returns.delete_many({"id": {"$in": rets}})
    db.sales_direct_notes.delete_many({"id": {"$in": note_ids}})
    for coll in ("fg_cost_consumptions", "fg_cost_layers", "rahaza_material_stock", "rahaza_stock_ledger", "rahaza_fg_movements"):
        db[coll].delete_many({"material_id": MAT})
    db.rahaza_materials.delete_one({"id": MAT})
    c = db.rahaza_customers.find_one({"id": S.get("cust")})
    if c:
        db.rahaza_coa_accounts.delete_many({"code": c.get("ar_account_code", "__none__")})
        db.rahaza_customers.delete_one({"id": c["id"]})
    assert _bal()
