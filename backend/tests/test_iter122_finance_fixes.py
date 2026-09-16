"""Iter 122 — Finance regression suite.

Coverage:
1. HAPUS SALDO GANDA — POST /cash-accounts tidak menyimpan field `balance`; setiap
   GET /cash-accounts memakai saldo GL (balance_source 'gl'); AR payment & expense
   dgn account_id → balance_mutasi tetap == balance (diff 0). Cash-flow report 200.
2. RETUR RUSAK BERNILAI — WH return kondisi Rusak → aksi 'Karantina (Rusak)'
   → restock_location_code ZNA-KARANTINA, loss_unit_cost/loss_amount/loss_je_number
   terisi, JE return_damaged_loss Dr 6-1300 / Cr 5-1000 balanced; idempoten.
   Regresi kondisi Baik → cogs JE Dr 1-1404 / Cr 5-1000.
3. Skrip void_cn_marketplace_dobel.py — dry-run + --apply + re-run kandidat 0.
4. Kwitansi PDF — GET receipt.pdf AR/AP 200 application/pdf isi valid; 404 pid asing.
"""
import io
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PW = "Admin@123"


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


_state = {}


# ────────────────── (1) SATU SUMBER SALDO KAS = GL ──────────────────────
def test_1a_create_cash_account_no_balance_field(H, db):
    code = f"BCA-IT122-{int(time.time()) % 100000}"
    body = {"code": code, "name": f"BCA Uji Iter122 {code}", "type": "bank",
            "bank_name": "BCA", "opening_balance": 1_000_000}
    r = requests.post(f"{BASE_URL}/api/rahaza/cash-accounts", json=body, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    _state["cash"] = data
    assert data.get("balance") == 1_000_000, f"balance={data.get('balance')}"
    assert data.get("balance_source") == "gl"
    assert data.get("balance_mutasi") == 1_000_000
    assert data.get("balance_diff") == 0
    # Mongo dokumen: TIDAK menyimpan `balance`
    raw = db.rahaza_cash_accounts.find_one({"id": data["id"]})
    assert raw is not None
    assert "balance" not in raw, f"Field 'balance' tidak boleh ada di dokumen: {list(raw)}"


def test_1b_ar_payment_no_dollar_inc_balance(H, db):
    cash = _state["cash"]
    cust_code = f"CUST122{int(time.time()) % 100000}"
    r = requests.post(f"{BASE_URL}/api/rahaza/customers",
                      json={"code": cust_code, "name": f"Cust 122 {cust_code}"},
                      headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    cust = r.json()
    inv_body = {
        "customer_id": cust["id"],
        "invoice_date": "2026-09-06", "due_date": "2026-10-06",
        "items": [{"description": "Test 122", "qty": 1, "unit_price": 500_000}],
        "tax_pct": 0,
    }
    r = requests.post(f"{BASE_URL}/api/rahaza/ar-invoices", json=inv_body, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    inv = r.json()
    _state["ar_inv"] = inv
    r = requests.post(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/send", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    # Payment 300k pakai account_id
    r = requests.post(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payment",
                      json={"amount": 300_000, "date": "2026-09-06",
                            "account_id": cash["id"], "notes": "iter122 pay"},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text
    # GET cash-accounts → 1.300.000, diff 0
    r = requests.get(f"{BASE_URL}/api/rahaza/cash-accounts", headers=H, timeout=30)
    row = next(a for a in r.json() if a["id"] == cash["id"])
    assert row["balance"] == 1_300_000, f"balance={row['balance']}"
    assert row["balance"] == row["balance_mutasi"]
    assert row["balance_diff"] == 0
    # Dokumen Mongo tetap tanpa field `balance`
    raw = db.rahaza_cash_accounts.find_one({"id": cash["id"]})
    assert "balance" not in raw, f"tidak boleh $inc balance: {list(raw)}"


def test_1c_expense_no_dollar_inc_balance(H, db):
    cash = _state["cash"]
    r = requests.post(f"{BASE_URL}/api/rahaza/expenses",
                      json={"amount": 100_000, "date": "2026-09-06",
                            "category": "operasional",
                            "description": "Iter122 expense uji",
                            "account_id": cash["id"]},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE_URL}/api/rahaza/cash-accounts", headers=H, timeout=30)
    row = next(a for a in r.json() if a["id"] == cash["id"])
    assert row["balance"] == 1_200_000, f"balance={row['balance']}"
    assert row["balance"] == row["balance_mutasi"]
    assert row["balance_diff"] == 0
    raw = db.rahaza_cash_accounts.find_one({"id": cash["id"]})
    assert "balance" not in raw


def test_1d_cash_flow_report(H):
    r = requests.get(f"{BASE_URL}/api/rahaza/finance/reports/cash-flow"
                     f"?from_date=2026-09-01&to_date=2026-09-30",
                     headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    # closing/opening should be numeric
    for k in ("closing_cash", "opening_cash", "closing_cash_now"):
        if k in j:
            assert isinstance(j[k], (int, float)), f"{k}={j[k]!r}"


# ────────────────── (2) RETUR RUSAK BERNILAI ────────────────────────────
def _pick_fg(db):
    mat = db.rahaza_materials.find_one({"type": "fg", "hpp": {"$gt": 0}}, {"_id": 0})
    if not mat:
        mat = db.rahaza_materials.find_one({"type": "fg", "unit_cost": {"$gt": 0}}, {"_id": 0})
    return mat


def test_2a_damaged_return_karantina_loss_je(H, db):
    mat = _pick_fg(db)
    if not mat:
        pytest.skip("no FG w/ hpp")
    hpp = float(mat.get("hpp") or mat.get("unit_cost") or 0)
    body = {"return_type": "customer_refund",
            "order_number": f"ORD-IT122D-{int(time.time()) % 100000}",
            "resi_number": f"RSI-IT122D-{int(time.time()) % 100000}",
            "channel": "shopee", "material_id": mat["id"], "qty": 2}
    r = requests.post(f"{BASE_URL}/api/wh/returns", json=body, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    _state["wh_damaged_id"] = rid
    r = requests.post(f"{BASE_URL}/api/wh/returns/{rid}/receive",
                      json={"package_condition": "Rusak"}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/wh/returns/{rid}/inspect",
                      json={"item_condition": "Rusak",
                            "return_cause": "Kerusakan Ekspedisi",
                            "recommended_action": "Karantina (Rusak)"},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/wh/returns/{rid}/resolve",
                      json={"action_taken": "Karantina (Rusak)",
                            "item_condition": "Rusak", "restock_qty": 2},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc.get("restocked") is True, f"restocked={doc.get('restocked')}"
    assert doc.get("restock_location_code") == "ZNA-KARANTINA", doc.get("restock_location_code")
    assert doc.get("loss_unit_cost") == hpp, f"loss_unit_cost={doc.get('loss_unit_cost')} vs {hpp}"
    assert doc.get("loss_amount") == round(hpp * 2), f"loss_amount={doc.get('loss_amount')}"
    assert doc.get("loss_je_number"), f"loss_je_number kosong; err={doc.get('loss_post_error')}"
    assert doc.get("loss_post_error") in (None, ""), doc.get("loss_post_error")
    # karantina nilai 0 → tidak ada hpp_layer_id / cogs_je_number
    assert not doc.get("hpp_layer_id"), f"unexpected hpp_layer_id={doc.get('hpp_layer_id')}"
    assert not doc.get("cogs_je_number"), f"unexpected cogs_je_number={doc.get('cogs_je_number')}"

    # JE balanced Dr 6-1300 / Cr 5-1000
    je = db.rahaza_journal_entries.find_one({"je_number": doc["loss_je_number"]}, {"_id": 0})
    assert je, f"JE {doc['loss_je_number']} not found"
    assert je.get("source_module") == "return_damaged_loss"
    assert je.get("status") == "posted"
    dr = sum(l.get("debit", 0) for l in je["lines"])
    cr = sum(l.get("credit", 0) for l in je["lines"])
    assert round(dr, 2) == round(cr, 2) == round(hpp * 2, 2), f"Dr={dr} Cr={cr} exp={hpp*2}"
    codes = {(l["account_code"], "D" if l.get("debit", 0) > 0 else "C") for l in je["lines"]}
    assert ("6-1300", "D") in codes, f"Dr 6-1300 missing: {codes}"
    assert ("5-1000", "C") in codes, f"Cr 5-1000 missing: {codes}"


def test_2b_damaged_return_idempotent_no_double_je(H, db):
    rid = _state.get("wh_damaged_id")
    if not rid:
        pytest.skip("no damaged wh return in state")
    # Idempoten: hitung JE sumber whret_damaged:{id}
    src_ref = f"whret_damaged:{rid}"
    n = db.rahaza_journal_entries.count_documents(
        {"source_module": "return_damaged_loss", "source_ref": src_ref, "status": {"$ne": "voided"}})
    assert n == 1, f"expected 1 JE for damaged wh return, got {n}"


def test_2c_good_return_regression_cogs_je(H, db):
    mat = _pick_fg(db)
    if not mat:
        pytest.skip("no FG w/ hpp")
    body = {"return_type": "customer_refund",
            "order_number": f"ORD-IT122G-{int(time.time()) % 100000}",
            "resi_number": f"RSI-IT122G-{int(time.time()) % 100000}",
            "channel": "shopee", "material_id": mat["id"], "qty": 1}
    r = requests.post(f"{BASE_URL}/api/wh/returns", json=body, headers=H, timeout=30)
    rid = r.json()["id"]
    requests.post(f"{BASE_URL}/api/wh/returns/{rid}/receive",
                  json={"package_condition": "Baik"}, headers=H, timeout=30)
    r = requests.post(f"{BASE_URL}/api/wh/returns/{rid}/inspect",
                      json={"item_condition": "Baik",
                            "return_cause": "Kesalahan Customer",
                            "recommended_action": "Restock ke Gudang"},
                      headers=H, timeout=30)
    assert r.status_code == 200
    r = requests.post(f"{BASE_URL}/api/wh/returns/{rid}/resolve",
                      json={"action_taken": "Restock ke Gudang",
                            "item_condition": "Baik", "restock_qty": 1},
                      headers=H, timeout=30)
    assert r.status_code == 200
    doc = r.json()
    assert doc.get("restock_location_code") == "ZNA-FG"
    assert doc.get("hpp_layer_id"), "hpp_layer_id kosong"
    assert doc.get("cogs_je_number")
    assert not doc.get("loss_je_number")


# ────────────────── (3) SKRIP VOID CN MARKETPLACE DOBEL ─────────────────
async def _seed_cn(db):
    """Buat CN simulasi + JE via _create_posted_je."""
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.rahaza_posting import _create_posted_je
    from datetime import date

    adb = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    # Cari akun AR postable
    ar_acc = await adb.rahaza_coa_accounts.find_one(
        {"code": {"$regex": "^1-1301"}, "active": True, "is_group": {"$ne": True}}, {"_id": 0})
    if not ar_acc:
        # fallback: buat akun sub AR sederhana? cari 1-13xx generik
        ar_acc = await adb.rahaza_coa_accounts.find_one(
            {"type": "asset", "active": True, "is_group": {"$ne": True},
             "code": {"$regex": "^1-13"}}, {"_id": 0})
    if not ar_acc:
        return None
    cn_id = str(uuid.uuid4())
    source_ref = f"cn:{cn_id}"
    lines = [
        {"account_code": "4-1200", "debit": 12345, "credit": 0, "description": "Iter122 sim CN dr"},
        {"account_code": ar_acc["code"], "debit": 0, "credit": 12345, "description": "Iter122 sim CN cr"},
    ]
    res = await _create_posted_je(adb, date(2026, 9, 6),
                                  "Iter122 simulasi CN marketplace dobel",
                                  "credit_note", source_ref, lines,
                                  {"id": "test", "name": "iter122-test"})
    if not res.get("ok"):
        return None
    now = datetime.now(timezone.utc)
    doc = {
        "id": cn_id,
        "cn_number": f"CN-SIM-IT122-{int(time.time())%100000}",
        "return_id": f"ret-sim-{cn_id[:8]}",
        "total": 12345,
        "gl_je_id": res["je_id"],
        "gl_je_number": res["je_number"],
        "gl_posted_at": now,
        "gl_mode": "posted",
        "created_at": now,
    }
    await adb.rahaza_credit_notes.insert_one(doc)
    return {"cn_id": cn_id, "je_id": res["je_id"], "je_number": res["je_number"]}


def test_3_void_cn_script(db):
    import asyncio
    seed = asyncio.run(_seed_cn(db))
    if not seed:
        pytest.skip("cannot seed CN (missing AR postable account)")
    cn_id = seed["cn_id"]

    def _run(*args):
        return subprocess.run(
            ["python3", "/app/scripts/void_cn_marketplace_dobel.py", *args],
            cwd="/app/backend", capture_output=True, text=True, timeout=60)

    # DRY-RUN → kandidat >=1
    r = _run()
    assert r.returncode == 0, r.stderr or r.stdout
    m = re.search(r"kandidat[^:]*:\s*(\d+)", r.stdout)
    assert m and int(m.group(1)) >= 1, f"dry-run kandidat: {r.stdout}"
    # DB tidak berubah → JE masih posted, CN gl_mode 'posted'
    je = db.rahaza_journal_entries.find_one({"id": seed["je_id"]}, {"_id": 0})
    assert je and je.get("status") == "posted"
    cn = db.rahaza_credit_notes.find_one({"id": cn_id}, {"_id": 0})
    assert cn.get("gl_mode") == "posted"

    # --apply
    r = _run("--apply")
    assert r.returncode == 0, r.stderr or r.stdout
    je = db.rahaza_journal_entries.find_one({"id": seed["je_id"]}, {"_id": 0})
    assert je.get("status") == "voided", f"status={je.get('status')}"
    n_lines = db.rahaza_journal_lines.count_documents({"je_id": seed["je_id"]})
    assert n_lines == 0, f"leftover lines={n_lines}"
    cn = db.rahaza_credit_notes.find_one({"id": cn_id}, {"_id": 0})
    assert cn.get("gl_mode") == "settlement"
    assert cn.get("gl_je_id") in (None, "", 0)
    assert cn.get("gl_voided_je_number") == seed["je_number"]

    # Re-run --apply → kandidat 0
    r = _run("--apply")
    m = re.search(r"kandidat[^:]*:\s*(\d+)", r.stdout)
    assert m and int(m.group(1)) == 0, f"expected 0 kandidat on re-run:\n{r.stdout}"

    # Cleanup simulasi
    db.rahaza_credit_notes.delete_one({"id": cn_id})
    db.rahaza_journal_entries.delete_one({"id": seed["je_id"]})


# ────────────────── (4) KWITANSI PDF ────────────────────────────────────
def _has_pymupdf():
    try:
        import pymupdf  # noqa: F401
        return True
    except Exception:
        return False


def test_4a_ar_receipt_pdf(H, db):
    inv = _state.get("ar_inv")
    assert inv, "AR invoice not seeded"
    r = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments",
                     headers=H, timeout=30)
    assert r.status_code == 200
    pays = r.json()
    assert pays, "no AR payments"
    pid = pays[0]["id"]
    je_num = pays[0].get("gl_je_number") or ""
    r = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments/{pid}/receipt.pdf",
                     headers=H, timeout=60)
    assert r.status_code == 200, r.text[:400]
    assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
    assert len(r.content) > 1024, f"PDF size={len(r.content)}"
    assert r.content[:4] == b"%PDF", "not a PDF"
    if _has_pymupdf():
        import pymupdf
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        txt = "".join(p.get_text() for p in doc)
        assert "KWITANSI" in txt.upper(), f"missing KWITANSI keyword; got: {txt[:400]}"
        assert (inv.get("invoice_number") or "") in txt, "invoice number absent in PDF"
        if je_num:
            assert je_num in txt, f"JE number {je_num} absent in PDF"

    # 404 pid asing
    r404 = requests.get(f"{BASE_URL}/api/rahaza/ar-invoices/{inv['id']}/payments/"
                        f"random-{uuid.uuid4()}/receipt.pdf", headers=H, timeout=30)
    assert r404.status_code == 404

    # kind lain → 404
    r_bad = requests.get(f"{BASE_URL}/api/rahaza/xx-invoices/{inv['id']}/payments/{pid}/receipt.pdf",
                         headers=H, timeout=30)
    assert r_bad.status_code == 404


def test_4b_ap_receipt_pdf(H, db):
    # Cari AP invoice non-draft dengan payment; kalau tidak ada buat sendiri.
    cash = _state.get("cash")
    body = {"vendor_name": f"Vendor IT122 {int(time.time())%1000}",
            "issue_date": "2026-09-06", "due_date": "2026-10-06",
            "items": [{"description": "AP test", "qty": 1, "unit_price": 200_000}],
            "tax_pct": 0}
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices", json=body, headers=H, timeout=30)
    assert r.status_code in (200, 201), r.text
    ap = r.json()
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/status",
                      json={"status": "sent"}, headers=H, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payment",
                      json={"amount": 100_000, "date": "2026-09-06",
                            "account_id": cash["id"] if cash else None,
                            "notes": "iter122 ap"},
                      headers=H, timeout=30)
    assert r.status_code == 200, r.text

    rp = requests.get(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payments",
                      headers=H, timeout=30)
    assert rp.status_code == 200
    pays = rp.json()
    assert pays
    pid = pays[0]["id"]
    r = requests.get(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payments/{pid}/receipt.pdf",
                     headers=H, timeout=60)
    assert r.status_code == 200, r.text[:400]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 1024
    if _has_pymupdf():
        import pymupdf
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        txt = "".join(p.get_text() for p in doc)
        assert "BUKTI PEMBAYARAN" in txt.upper(), f"missing keyword; text head: {txt[:400]}"

    # 404
    r404 = requests.get(f"{BASE_URL}/api/rahaza/ap-invoices/{ap['id']}/payments/"
                        f"random-{uuid.uuid4()}/receipt.pdf", headers=H, timeout=30)
    assert r404.status_code == 404
