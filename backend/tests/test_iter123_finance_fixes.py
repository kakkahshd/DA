"""Iter 123 — Bukti eksekusi perbaikan finance (review 2026-09-05 sisa).

B-11  bayar AP draft → 400, invoice tetap draft tanpa GL; setelah send → 200.
B-13  L/R ikut akun nonaktif bersaldo.
H-10  post_credit_note: CN ber-PPN → Dr 4-1200 (DPP) + Dr 2-1400 (PPN) / Cr AR (total).
M-04/B-09  post_cmt_ap_invoice: penalti mengurangi biaya & hutang, tanggal JE = invoice_date, net_amount diperbarui.
M-03  7-1xx bertipe COGS & tampil di grup HPP L/R.
B-10  post_ap_invoice source gr + gl_price_variance → GRNI = nilai GR, selisih ke 5-1900.
M-05  jurnal pencairan: potongan lain & penyesuaian negatif → Dr 6-2900, positif → Cr 7-4000.
L-03  payroll pay tanpa bank_account_code memakai profil (bukan hard-code).
B-12  post_inventory_issue memakai unit_cost_applied, dan menstempel bila kosong.
Kwitansi PDF AR 200 + 404 pid asing.
Cash account kode ganda → 409.
Regresi cepat: TB seimbang, neraca 200, JE posted seimbang.
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import date, datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PW = "Admin@123"
TEST_USER = {"id": "iter123-test", "name": "iter123-test", "role": "superadmin"}
_state = {}


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def db():
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro_fn, *args):
    """Jalankan coroutine posting dengan AsyncIOMotorClient di loop baru."""
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _inner():
        adb = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        return await coro_fn(adb, *args)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


def _je(db, je_number):
    je = db.rahaza_journal_entries.find_one({"je_number": je_number}, {"_id": 0})
    assert je, f"JE {je_number} tidak ada"
    return je


def _line(je, code, side):
    return round(sum(l.get(side, 0) for l in je["lines"] if l["account_code"] == code), 2)


def _balanced(je):
    d = round(sum(l.get("debit", 0) for l in je["lines"]), 2)
    c = round(sum(l.get("credit", 0) for l in je["lines"]), 2)
    assert d == c, f"JE {je['je_number']} Dr={d} Cr={c}"
    return d


def _cleanup_je(db, je_number):
    je = db.rahaza_journal_entries.find_one({"je_number": je_number}, {"_id": 0, "id": 1})
    if je:
        db.rahaza_journal_lines.delete_many({"je_id": je["id"]})
        db.rahaza_journal_entries.delete_one({"id": je["id"]})


# ───────────── Cash account 409 + fixture kas untuk tes lain ─────────────
def test_00_cash_account_duplicate_code_409(H):
    code = f"KAS-IT123-{int(time.time()) % 100000}"
    body = {"code": code, "name": f"Kas Uji Iter123 {code}", "type": "bank",
            "bank_name": "BCA", "opening_balance": 5_000_000}
    r = requests.post(f"{BASE_URL}/api/rahaza/cash-accounts", json=body, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    _state["cash"] = r.json()
    r2 = requests.post(f"{BASE_URL}/api/rahaza/cash-accounts", json=body, headers=H, timeout=30)
    assert r2.status_code == 409, f"kode ganda harus 409, dapat {r2.status_code}: {r2.text}"


# ───────────── B-11: bayar AP draft ditolak ─────────────
def test_01_b11_ap_payment_on_draft_rejected(H, db):
    body = {"vendor_name": f"Vendor IT123 {int(time.time()) % 1000}",
            "issue_date": "2026-09-07", "due_date": "2026-10-07",
            "items": [{"description": "AP draft test", "qty": 1, "unit_price": 250_000}],
            "tax_pct": 0}
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices", json=body, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    ap = r.json()
    assert (ap.get("status") or "").lower() == "draft", ap.get("status")
    _state["ap"] = ap

    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payment",
                      json={"amount": 100_000, "date": "2026-09-07",
                            "account_id": _state["cash"]["id"]}, headers=H, timeout=30)
    assert r.status_code == 400, f"harus 400, dapat {r.status_code}: {r.text}"
    assert "draft" in r.text.lower()
    raw = db.rahaza_ap_invoices.find_one({"id": ap["id"]}, {"_id": 0})
    assert raw["status"] == "draft"
    assert not raw.get("gl_je_id"), "invoice draft tidak boleh diposting diam-diam"
    assert float(raw.get("paid_amount") or 0) == 0
    n = db.rahaza_journal_entries.count_documents({"source_ref": f"ap:{ap['id']}"})
    assert n == 0, "tidak boleh ada JE ap_invoice untuk draft"


def test_02_b11_ap_payment_after_send_ok(H, db):
    ap = _state["ap"]
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/status",
                      json={"status": "sent"}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payment",
                      json={"amount": 100_000, "date": "2026-09-07",
                            "account_id": _state["cash"]["id"]}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    raw = db.rahaza_ap_invoices.find_one({"id": ap["id"]}, {"_id": 0})
    assert raw["status"] == "partial_paid"
    assert float(raw["paid_amount"]) == 100_000


# ───────────── B-13: L/R ikut akun nonaktif bersaldo ─────────────
def test_03_b13_profit_loss_includes_inactive_account(H, db):
    from routes.rahaza_posting import _create_posted_je
    code = "6-2900"
    acc = db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0})
    assert acc and acc.get("type") == "EXPENSE"
    lines = [{"account_code": code, "debit": 7_777, "credit": 0, "description": "Iter123 B-13"},
             {"account_code": "1-1201", "debit": 0, "credit": 7_777, "description": "Iter123 B-13"}]
    res = _run(_create_posted_je, date(2026, 9, 7), "Iter123 B-13 uji akun nonaktif",
               "manual", f"it123-b13:{uuid.uuid4()}", lines, TEST_USER)
    assert res.get("ok"), res
    _state["b13_je"] = res["je_number"]
    try:
        db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {"active": False}})
        r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/profit-loss"
                         f"?from_date=2026-09-01&to_date=2026-09-30", headers=H, timeout=60)
        assert r.status_code == 200, r.text
        rows = r.json()["groups"]["expense"]["accounts"]
        row = next((x for x in rows if x["code"] == code), None)
        assert row, f"akun nonaktif {code} hilang dari L/R: {[x['code'] for x in rows]}"
        assert row["debit"] >= 7_777
    finally:
        db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {"active": True}})


# ───────────── H-10: CN ber-PPN membalik PPN Keluaran ─────────────
def test_04_h10_credit_note_reverses_vat(db):
    from routes.rahaza_posting import post_credit_note
    cn_id = str(uuid.uuid4())
    cn = {"id": cn_id, "cn_number": f"CN-IT123-{int(time.time()) % 100000}",
          "total": 111_000, "tax_amount": 11_000, "issue_date": "2026-09-07",
          "platform": "Finance"}
    db.rahaza_credit_notes.insert_one({**cn, "created_at": datetime.now(timezone.utc)})
    res = _run(post_credit_note, cn, TEST_USER)
    assert res.get("ok"), res
    je = _je(db, res["je_number"])
    _state["h10_je"] = res["je_number"]
    assert _balanced(je) == 111_000
    assert _line(je, "4-1200", "debit") == 100_000, je["lines"]
    assert _line(je, "2-1400", "debit") == 11_000, je["lines"]
    cr_total = round(sum(l.get("credit", 0) for l in je["lines"]), 2)
    assert cr_total == 111_000
    db.rahaza_credit_notes.delete_one({"id": cn_id})


# ───────────── M-04/B-09: penalti CMT mengurangi biaya & hutang; tanggal akrual ─────────────
def test_05_m04_b09_cmt_ap_penalty_and_accrual_date(db):
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    pid = str(uuid.uuid4())
    pay = {"id": pid, "payment_code": f"CMT-IT123-{int(time.time()) % 100000}",
           "cmt_name": "CMT Uji Iter123", "subtotal": 1_000_000, "total_amount": 1_000_000,
           "total_penalty": 50_000, "invoice_date": "2026-08-15", "payment_date": "2026-09-07"}
    db.dewi_cmt_payments.insert_one({**pay, "created_at": datetime.now(timezone.utc)})
    res = _run(post_cmt_ap_invoice, pay, TEST_USER)
    assert res.get("ok"), res
    je = _je(db, res["je_number"])
    _state["m04_je"] = res["je_number"]
    assert _balanced(je) == 950_000, je["lines"]
    assert _line(je, "4-9000", "credit") == 0, "penalti tidak boleh ke pendapatan lain"
    assert _line(je, "7-120", "debit") == 950_000, je["lines"]
    assert str(je.get("je_date") or je.get("date"))[:10] == "2026-08-15", je.get("je_date")
    doc = db.dewi_cmt_payments.find_one({"id": pid}, {"_id": 0})
    assert float(doc.get("net_amount")) == 950_000
    assert doc.get("gl_je_number") == res["je_number"]
    db.dewi_cmt_payments.delete_one({"id": pid})


# ───────────── M-03: 7-1xx = COGS ─────────────
def test_06_m03_maklon_cost_accounts_are_cogs(H, db):
    rows = list(db.rahaza_coa_accounts.find({"code": {"$regex": "^7-1[0-9]{2}$"}}, {"_id": 0, "code": 1, "type": 1}))
    assert rows, "akun 7-1xx tidak ada"
    bad = [r["code"] for r in rows if r["type"] != "COGS"]
    assert not bad, f"masih bertipe non-COGS: {bad}"
    r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/profit-loss"
                     f"?from_date=2026-08-01&to_date=2026-08-31", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    g = r.json()["groups"]
    cogs_codes = {x["code"] for x in g["cogs"]["accounts"]}
    exp_codes = {x["code"] for x in g["expense"]["accounts"]}
    assert "7-120" in cogs_codes, "7-120 harus di grup HPP"
    assert "7-120" not in exp_codes
    row = next(x for x in g["cogs"]["accounts"] if x["code"] == "7-120")
    assert row["debit"] >= 950_000, "JE CMT Agustus (M-04) harus masuk HPP maklon"


# ───────────── B-10: selisih harga AP vs GR → PPV ─────────────
def test_07_b10_ap_from_gr_price_variance_to_ppv(db):
    from routes.rahaza_posting import post_ap_invoice
    inv_id = str(uuid.uuid4())
    inv = {"id": inv_id, "invoice_number": f"AP-IT123-{int(time.time()) % 100000}",
           "vendor_name": "Supplier Uji Iter123", "source": "gr", "gr_ids": ["gr-sim"],
           "subtotal": 105_000, "tax_amount": 0, "total": 105_000,
           "gl_price_variance": 5_000, "issue_date": "2026-09-07", "status": "sent"}
    db.rahaza_ap_invoices.insert_one({**inv, "created_at": datetime.now(timezone.utc)})
    res = _run(post_ap_invoice, inv, TEST_USER)
    assert res.get("ok"), res
    je = _je(db, res["je_number"])
    _state["b10_je"] = res["je_number"]
    assert _balanced(je) == 105_000
    assert _line(je, "2-1150", "debit") == 100_000, je["lines"]
    assert _line(je, "5-1900", "debit") == 5_000, je["lines"]
    cr = [l for l in je["lines"] if l.get("credit", 0) > 0]
    assert len(cr) == 1 and cr[0]["credit"] == 105_000 and cr[0]["account_code"].startswith("2-1100")
    db.rahaza_ap_invoices.delete_one({"id": inv_id})


# ───────────── M-05: pencairan — potongan lain & penyesuaian dua arah ─────────────
def _marketing_account(H):
    r = requests.get(f"{BASE_URL}/api/marketing/accounts", headers=H, timeout=30)
    if r.status_code == 200:
        rows = r.json() if isinstance(r.json(), list) else r.json().get("items") or r.json().get("accounts") or []
        act = [a for a in rows if a.get("is_active", True)]
        if act:
            return act[0]
    code = f"IT123-{int(time.time()) % 10000}"
    r = requests.post(f"{BASE_URL}/api/marketing/accounts",
                      json={"account_code": code, "account_name": f"Toko Uji {code}", "platform": "shopee"},
                      headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_08_m05_settlement_journal_other_expense_two_way(H, db):
    acc = _marketing_account(H)
    sid = f"SET-IT123-{int(time.time()) % 100000}"
    body = {"account_id": acc["id"], "platform": acc.get("platform") or "shopee", "settlement_id": sid,
            "settlement_date": "2026-09-07", "gross_sales": 1_000_000, "refunds": 0,
            "seller_discount": 0, "shipping_subsidy": 20_000, "platform_commission": 50_000,
            "platform_service_fee": 0, "affiliate_commission": 0, "ads_deduction": 0,
            "other_deductions": 30_000, "other_deductions_note": "Denda platform",
            "adjustments": -10_000, "net_payout": 930_000}
    r = requests.post(f"{BASE_URL}/api/marketing/settlements", json=body, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    doc_id = doc.get("id") or (doc.get("data") or {}).get("id")
    assert doc_id, doc
    r = requests.post(f"{BASE_URL}/api/marketing/settlements/{doc_id}/journal", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("je_status") == "draft"
    je = _je(db, j["je_number"])
    _state["m05_je"] = j["je_number"]
    _balanced(je)
    assert _line(je, "6-2900", "debit") == 40_000, je["lines"]      # 30k potongan lain + 10k penyesuaian (−)
    assert _line(je, "7-4000", "credit") == 20_000, je["lines"]     # subsidi ongkir; penyesuaian (+) = 0
    assert _line(je, "7-4000", "debit") == 0, "akun pendapatan lain tidak boleh dipakai dua arah"
    db.marketing_settlements.delete_one({"id": doc_id})


# ───────────── L-03: bank payroll dari profil, bukan hard-code ─────────────
def test_09_l03_payroll_pay_bank_default_from_profile(H):
    src = open("/app/backend/routes/rahaza_payroll_runs.py", encoding="utf-8").read()
    assert 'or "1-1201"' not in src, "hard-code default bank 1-1201 masih ada di payroll pay"
    assert "credit_bank_default" in src
    r = requests.post(f"{BASE_URL}/api/rahaza/payroll-runs/run-tidak-ada-it123/pay",
                      json={"payment_date": "2026-09-07"}, headers=H, timeout=30)
    assert r.status_code == 404, f"{r.status_code} {r.text}"


# ───────────── B-12: nilai bahan saat transaksi ─────────────
def test_10_b12_material_issue_uses_unit_cost_applied(db):
    from routes.rahaza_posting import post_inventory_issue
    mat = db.rahaza_materials.find_one({"type": {"$ne": "fg"}, "unit_cost": {"$gt": 0}}, {"_id": 0})
    if not mat:
        pytest.skip("tidak ada bahan dengan unit_cost")
    master_cost = float(mat["unit_cost"])
    applied_cost = master_cost + 123  # berbeda dari master → harus menang
    now = datetime.now(timezone.utc)

    mi1 = {"id": str(uuid.uuid4()), "mi_number": f"MI-IT123A-{int(time.time()) % 100000}",
           "issued_at": "2026-09-07T08:00:00+00:00",
           "items": [{"material_id": mat["id"], "qty_issued": 10, "unit_cost_applied": applied_cost}]}
    db.rahaza_material_issues.insert_one({**mi1, "created_at": now})
    res = _run(post_inventory_issue, mi1, TEST_USER)
    assert res.get("ok"), res
    je = _je(db, res["je_number"])
    _state["b12_je_a"] = res["je_number"]
    assert _balanced(je) == round(10 * applied_cost, 2), f"harus pakai unit_cost_applied, bukan master {master_cost}"
    assert _line(je, "1-1403", "debit") == round(10 * applied_cost, 2)
    assert _line(je, "1-1401", "credit") == round(10 * applied_cost, 2)

    mi2 = {"id": str(uuid.uuid4()), "mi_number": f"MI-IT123B-{int(time.time()) % 100000}",
           "issued_at": "2026-09-07T08:00:00+00:00",
           "items": [{"material_id": mat["id"], "qty_issued": 3}]}
    db.rahaza_material_issues.insert_one({**mi2, "created_at": now})
    res = _run(post_inventory_issue, mi2, TEST_USER)
    assert res.get("ok"), res
    _state["b12_je_b"] = res["je_number"]
    stamped = db.rahaza_material_issues.find_one({"id": mi2["id"]}, {"_id": 0})
    assert float(stamped["items"][0].get("unit_cost_applied") or 0) == master_cost, stamped["items"]
    db.rahaza_material_issues.delete_many({"id": {"$in": [mi1["id"], mi2["id"]]}})


# ───────────── Kwitansi PDF ─────────────
def test_11_ar_receipt_pdf(H, db):
    cust_code = f"CUST123{int(time.time()) % 100000}"
    r = requests.post(f"{BASE_URL}/api/rahaza/customers",
                      json={"code": cust_code, "name": f"Cust 123 {cust_code}"}, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    cust = r.json()
    r = requests.post(f"{BASE_URL}/api/rahaza/ar-invoices",
                      json={"customer_id": cust["id"], "invoice_date": "2026-09-07", "due_date": "2026-10-07",
                            "items": [{"description": "Test 123", "qty": 1, "unit_price": 400_000}], "tax_pct": 0},
                      headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    inv = r.json()
    _state["ar_inv"] = inv
    assert requests.post(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/send", headers=H, timeout=30).status_code == 200
    r = requests.post(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payment",
                      json={"amount": 400_000, "date": "2026-09-07", "account_id": _state["cash"]["id"]},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text
    pays = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments", headers=H, timeout=30).json()
    assert pays
    pid = pays[0]["id"]
    r = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments/{pid}/receipt.pdf", headers=H, timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF" and len(r.content) > 1024
    import pymupdf
    txt = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
    assert "KWITANSI" in txt.upper()
    assert inv["invoice_number"] in txt
    r404 = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments/x-{uuid.uuid4()}/receipt.pdf",
                        headers=H, timeout=30)
    assert r404.status_code == 404


# ───────────── Regresi cepat + bersih-bersih ─────────────
def test_12_quick_regression_gl_balanced(H, db):
    r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/trial-balance?as_of=2026-12-31", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    td, tc = j["totals"]["end_debit"], j["totals"]["end_credit"]
    assert round(float(td), 2) == round(float(tc), 2), f"TB Dr={td} Cr={tc}"
    assert j["balanced"] is True, j["totals"]
    assert j["meta"]["to"] == "2026-12-31", "as_of harus dihormati"
    # akun nonaktif bersaldo harus ikut di TB
    assert any(row["code"] == "1-1301-CUST-0005" for row in j["rows"]), "akun nonaktif bersaldo hilang dari TB"
    r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/balance-sheet?as_of=2026-12-31", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE_URL}/api/rahaza/cash-accounts", headers=H, timeout=30)
    assert r.status_code == 200
    row = next(a for a in r.json() if a["id"] == _state["cash"]["id"])
    assert row["balance"] == 5_000_000 - 100_000 + 400_000, row
    assert row["balance_diff"] == 0
    unb = [e["je_number"] for e in db.rahaza_journal_entries.find({"status": "posted"}, {"_id": 0, "je_number": 1, "lines": 1})
           if round(sum(l.get("debit", 0) for l in e["lines"]) - sum(l.get("credit", 0) for l in e["lines"]), 2) != 0]
    assert not unb, f"JE posted tidak seimbang: {unb}"
    for k in ("b13_je", "h10_je", "m04_je", "b10_je", "m05_je", "b12_je_a", "b12_je_b"):
        if _state.get(k):
            _cleanup_je(db, _state[k])
