"""
Iter 113 — H-02 payroll per komponen (audit finance 2026-09-04).
  1. post_payroll_run: Dr 6-2100 (gross − late/LWOP) · Cr 2-1200 net + kasbon · Cr 2-1301 PPh21 · Cr 2-1500 BPJS; seimbang; idempoten.
  2. Komponen tidak konsisten (total_deductions ≠ Σ komponen) → ok=False + post_error tersimpan, TIDAK ada JE.
  3. POST /pay-bpjs & /pay-pph21 memakai akun liabilitas dari mapping (2-1500 / 2-1301) dan total dari agregator yang sama;
     sesudahnya saldo 2-1500/2-1301 dari run ini = 0 (kredit finalize − debit bayar).
Data uji sintetis (run + payslips) dibersihkan sendiri.
"""
import asyncio
import os
import sys
import uuid

import pytest
import requests
from pymongo import MongoClient
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
db = MongoClient(os.environ.get("MONGO_URL") or be["MONGO_URL"])[os.environ.get("DB_NAME") or be["DB_NAME"]]
SFX = uuid.uuid4().hex[:6]
RUN_ID = f"run-qa-{SFX}"
RUN_BAD = f"run-qa-bad-{SFX}"
S = {"je_ids": []}

SLIPS = [
    {"gross_pay": 5_000_000, "deductions_total": 350_000, "net_pay": 4_650_000,
     "deductions": [{"type": "pph21", "amount": 100_000}, {"type": "bpjs_kesehatan", "amount": 50_000},
                    {"type": "bpjs_jht", "amount": 100_000}, {"type": "kasbon", "amount": 75_000}, {"type": "late", "amount": 25_000}]},
    {"gross_pay": 3_000_000, "deductions_total": 60_000, "net_pay": 2_940_000,
     "deductions": [{"type": "bpjs_jp", "amount": 30_000}, {"type": "lwop", "amount": 30_000}]},
]


def _login():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@garment.com", "password": "Admin@123"}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _seed_run(run_id, slips, **over):
    db.rahaza_payslips.delete_many({"run_id": run_id})
    for i, s in enumerate(slips):
        db.rahaza_payslips.insert_one({"id": f"slip-{run_id}-{i}", "run_id": run_id, "employee_id": f"emp-qa-{i}",
                                       "employee_name": f"QA {i}", **s})
    doc = {"id": run_id, "run_number": f"PR-QA-{run_id}", "period_from": "2026-08-01", "period_to": "2026-08-31",
           "status": "finalized", "total_gross": sum(s["gross_pay"] for s in slips),
           "total_deductions": sum(s["deductions_total"] for s in slips), "total_net": sum(s["net_pay"] for s in slips)}
    doc.update(over)
    db.rahaza_payroll_runs.replace_one({"id": run_id}, doc, upsert=True)
    return doc


def _post(run):
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.rahaza_posting import post_payroll_run

    async def run_it():
        adb = AsyncIOMotorClient(be["MONGO_URL"])[be["DB_NAME"]]
        return await post_payroll_run(adb, run, {"id": "qa", "name": "QA"})
    return asyncio.run(run_it())


def _line(je, code, desc_part=None):
    for ln in je["lines"]:
        if ln["account_code"] == code and (desc_part is None or desc_part in ln["description"]):
            return ln
    return None


def test_00_deduction_totals():
    from routes.rahaza_posting import payroll_deduction_totals
    t = payroll_deduction_totals(SLIPS)
    assert t == {"pph21": 100_000, "bpjs": 180_000, "kasbon": 75_000, "other": 55_000,
                 "by_type": {"pph21": 100_000, "bpjs_kesehatan": 50_000, "bpjs_jht": 100_000, "kasbon": 75_000,
                             "late": 25_000, "bpjs_jp": 30_000, "lwop": 30_000}}


def test_01_post_per_component():
    run = _seed_run(RUN_ID, SLIPS)
    r = _post(run)
    assert r.get("ok"), r
    S["je_ids"].append(r["je_id"])
    je = db.rahaza_journal_entries.find_one({"id": r["je_id"]}, {"_id": 0})
    assert je["status"] == "posted" and je["total_debit"] == je["total_credit"] == 7_945_000
    assert _line(je, "6-2100")["debit"] == 7_945_000  # 8.000.000 − late 25.000 − lwop 30.000
    assert _line(je, "2-1200", "Net")["credit"] == 7_590_000
    assert _line(je, "2-1200", "kasbon")["credit"] == 75_000
    assert _line(je, "2-1301")["credit"] == 100_000
    assert _line(je, "2-1500")["credit"] == 180_000
    assert len(db.rahaza_journal_lines.find({"je_id": je["id"]}).distinct("account_code")) == 4
    again = _post(run)
    assert again.get("already_posted") and again["je_id"] == r["je_id"]
    saved = db.rahaza_payroll_runs.find_one({"id": RUN_ID}, {"_id": 0})
    assert saved["gl_je_id"] == r["je_id"] and not saved.get("post_error")


def test_02_inconsistent_components_rejected():
    run = _seed_run(RUN_BAD, SLIPS, total_deductions=999_999)
    r = _post(run)
    assert r.get("ok") is False and "tidak konsisten" in r["error"], r
    assert db.rahaza_journal_entries.count_documents({"source_ref": f"payroll:{RUN_BAD}"}) == 0
    assert "tidak konsisten" in (db.rahaza_payroll_runs.find_one({"id": RUN_BAD}, {"_id": 0})["post_error"] or "")


def test_03_pay_bpjs_and_pph21_use_mapping(H):
    r = requests.post(f"{BASE}/api/rahaza/payroll-runs/{RUN_ID}/pay-bpjs", headers=H, timeout=60,
                      json={"payment_date": "2026-09-05"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bpjs_payment_status"] == "paid" and d["bpjs_payment_amount"] == 180_000, d
    je = db.rahaza_journal_entries.find_one({"je_number": d["bpjs_payment_je"]}, {"_id": 0})
    S["je_ids"].append(je["id"])
    assert _line(je, "2-1500")["debit"] == 180_000 and _line(je, "1-1201")["credit"] == 180_000

    r = requests.post(f"{BASE}/api/rahaza/payroll-runs/{RUN_ID}/pay-pph21", headers=H, timeout=60,
                      json={"payment_date": "2026-09-05"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pph21_payment_status"] == "paid" and d["pph21_payment_amount"] == 100_000, d
    je = db.rahaza_journal_entries.find_one({"je_number": d["pph21_payment_je"]}, {"_id": 0})
    S["je_ids"].append(je["id"])
    assert _line(je, "2-1301")["debit"] == 100_000 and _line(je, "1-1201")["credit"] == 100_000

    for code in ("2-1500", "2-1301"):
        rows = list(db.rahaza_journal_lines.find({"je_id": {"$in": S["je_ids"]}, "account_code": code}, {"_id": 0}))
        assert round(sum(x.get("credit", 0) - x.get("debit", 0) for x in rows), 2) == 0, (code, rows)

    assert requests.post(f"{BASE}/api/rahaza/payroll-runs/{RUN_ID}/pay-bpjs", headers=H, timeout=60,
                         json={"payment_date": "2026-09-05"}).status_code == 400


def test_04_balance_sheet_still_balanced(H):
    r = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H, timeout=120)
    assert r.status_code == 200 and r.json().get("balanced") is True, r.text


def test_zz_cleanup():
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": S["je_ids"]}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": S["je_ids"]}})
    db.rahaza_payslips.delete_many({"run_id": {"$in": [RUN_ID, RUN_BAD]}})
    db.rahaza_payroll_runs.delete_many({"id": {"$in": [RUN_ID, RUN_BAD]}})
    assert db.rahaza_journal_entries.count_documents({"source_ref": {"$regex": f"{SFX}"}}) == 0
    orphan = db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}})
    assert orphan == 0
