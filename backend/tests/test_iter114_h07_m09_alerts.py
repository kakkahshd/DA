"""
Iter 114 — M-09 tutup tahun · peringatan periode (H-07 dicabut iter 115: PO internal = stok sendiri).
Semua data uji sintetis dan dibersihkan sendiri (JE + cermin, periode 2024/2019, alerts, closings).
"""
import os
import sys
import uuid
from datetime import date

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
S = {"je_ids": [], "alert_ids": []}
YE = 2024


def _login(email="admin@garment.com", pw="Admin@123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login()


def _je(jid):
    return db.rahaza_journal_entries.find_one({"id": jid}, {"_id": 0})


def _line(je, code):
    return next((ln for ln in je["lines"] if ln["account_code"] == code), None)


# ───────────────────────── M-09 ─────────────────────────
def _post_je(H, d, lines, memo):
    r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, timeout=60, json={"date": d, "memo": memo, "lines": lines, "post": True})
    if r.status_code == 200:
        S["je_ids"].append(r.json()["id"])
    return r


def test_20_year_end_close(H):
    assert db.rahaza_periods.count_documents({"year": YE}) == 0
    assert requests.post(f"{BASE}/api/rahaza/periods/ensure-year", headers=H, json={"year": YE}, timeout=30).json()["created"] == 12
    r = _post_je(H, f"{YE}-06-15", [{"account_code": "1-1301", "debit": 1_000_000, "credit": 0}, {"account_code": "4-1100", "debit": 0, "credit": 1_000_000}], "QA YE revenue")
    assert r.status_code == 200, r.text
    r = _post_je(H, f"{YE}-07-15", [{"account_code": "6-2900", "debit": 400_000, "credit": 0}, {"account_code": "1-1201", "debit": 0, "credit": 400_000}], "QA YE expense")
    assert r.status_code == 200, r.text

    pv = requests.get(f"{BASE}/api/rahaza/year-end/preview?year={YE}", headers=H, timeout=30).json()
    assert pv["net_income"] == 600_000 and len(pv["open_periods"]) == 12 and pv["can_close"] is False
    r = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H, json={"year": YE}, timeout=30)
    assert r.status_code == 400 and "belum closed" in r.json()["detail"]

    for m in range(1, 13):
        assert requests.post(f"{BASE}/api/rahaza/periods/{YE}-{m:02d}/close", headers=H, timeout=30).status_code == 200
    pv = requests.get(f"{BASE}/api/rahaza/year-end/preview?year={YE}", headers=H, timeout=30).json()
    assert pv["can_close"] is True and pv["open_periods"] == []

    r = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H, json={"year": YE}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    S["je_ids"].append(d["je_id"])
    assert d["net_income"] == 600_000 and d["status"] == "closed"
    je = _je(d["je_id"])
    assert je["date"] == f"{YE}-12-31" and je["status"] == "posted" and je["source_module"] == "year_end_close"
    assert _line(je, "4-1100")["debit"] == 1_000_000 and _line(je, "6-2900")["credit"] == 400_000 and _line(je, "3-2000")["credit"] == 600_000

    # idempoten
    r = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H, json={"year": YE}, timeout=30)
    assert r.status_code == 400 and "sudah ditutup" in r.json()["detail"]
    # L/R tahun itu tetap menunjukkan laba (jurnal penutup dikecualikan), neraca seimbang & laba ditahan terisi
    pl = requests.get(f"{BASE}/api/rahaza/finance/reports/profit-loss?from={YE}-01-01&to={YE}-12-31", headers=H, timeout=60).json()
    assert pl["totals"]["net_income"] == 600_000, pl["totals"]
    bs = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet?as_of={YE}-12-31", headers=H, timeout=60).json()
    assert bs["balanced"] is True and bs["totals"]["current_earnings"] == 0
    assert any(a["code"] == "3-2000" and a["amount"] == 600_000 for a in bs["equity"]["accounts"])
    lst = requests.get(f"{BASE}/api/rahaza/year-end", headers=H, timeout=30).json()["closings"]
    assert any(c["year"] == YE and c["status"] == "closed" for c in lst)


def test_21_year_end_reverse(H):
    r = requests.post(f"{BASE}/api/rahaza/year-end/{YE}/reverse", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    je = db.rahaza_journal_entries.find_one({"source_ref": f"yearend:{YE}"}, {"_id": 0})
    assert je["status"] == "voided" and db.rahaza_journal_lines.count_documents({"je_id": je["id"]}) == 0
    assert requests.get(f"{BASE}/api/rahaza/year-end/preview?year={YE}", headers=H, timeout=30).json()["already_closed"] is False
    assert requests.post(f"{BASE}/api/rahaza/year-end/{YE}/reverse", headers=H, timeout=30).status_code == 404


def test_22_year_end_rbac():
    g = _login("gudang@dewiaditya.id", "Dewi@123")
    assert requests.post(f"{BASE}/api/rahaza/year-end/close", headers=g, json={"year": YE}, timeout=30).status_code == 403


# ───────────────────────── Peringatan periode ─────────────────────────
def test_30_period_alert_flow(H):
    db.rahaza_period_alerts.delete_many({"year": 2019})
    assert db.rahaza_periods.count_documents({"year": 2019}) == 0
    r = _post_je(H, "2019-03-01", [{"account_code": "1-1201", "debit": 1000, "credit": 0}, {"account_code": "6-2900", "debit": 0, "credit": 1000}], "QA alert")
    assert r.status_code == 400 and "belum dibuka" in r.json()["detail"]
    _post_je(H, "2019-03-02", [{"account_code": "1-1201", "debit": 1000, "credit": 0}, {"account_code": "6-2900", "debit": 0, "credit": 1000}], "QA alert 2")
    al = requests.get(f"{BASE}/api/rahaza/periods/alerts", headers=H, timeout=30).json()
    mine = [a for a in al["alerts"] if a["year"] == 2019]
    assert len(mine) == 1 and mine[0]["count"] == 2 and mine[0]["source_module"] == "manual_journal" and mine[0]["status"] == "open"
    S["alert_ids"].append(mine[0]["id"])
    # tombol "Buka tahun 2019" = ensure-year → alert otomatis resolved, posting kemudian jalan
    assert requests.post(f"{BASE}/api/rahaza/periods/ensure-year", headers=H, json={"year": 2019}, timeout=30).status_code == 200
    a = db.rahaza_period_alerts.find_one({"id": mine[0]["id"]}, {"_id": 0})
    assert a["status"] == "resolved" and a["resolved_via"] == "ensure-year"
    assert not [x for x in requests.get(f"{BASE}/api/rahaza/periods/alerts", headers=H, timeout=30).json()["alerts"] if x["year"] == 2019]
    r = _post_je(H, "2019-03-01", [{"account_code": "1-1201", "debit": 1000, "credit": 0}, {"account_code": "6-2900", "debit": 0, "credit": 1000}], "QA alert ok")
    assert r.status_code == 200, r.text


def test_31_alert_resolve_manual(H):
    db.rahaza_period_alerts.delete_many({"year": 2018})
    _post_je(H, "2018-01-10", [{"account_code": "1-1201", "debit": 1000, "credit": 0}, {"account_code": "6-2900", "debit": 0, "credit": 1000}], "QA alert 2018")
    a = db.rahaza_period_alerts.find_one({"year": 2018, "status": "open"}, {"_id": 0})
    assert a
    S["alert_ids"].append(a["id"])
    assert requests.post(f"{BASE}/api/rahaza/periods/alerts/{a['id']}/resolve", headers=H, timeout=30).status_code == 200
    assert requests.post(f"{BASE}/api/rahaza/periods/alerts/{a['id']}/resolve", headers=H, timeout=30).status_code == 404


def test_zz_cleanup():
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": S["je_ids"]}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": S["je_ids"]}})
    db.rahaza_year_end_closings.delete_many({"year": YE})
    db.rahaza_periods.delete_many({"year": {"$in": [YE, 2019]}})
    db.rahaza_period_alerts.delete_many({"year": {"$in": [2018, 2019]}})
    assert db.rahaza_journal_entries.count_documents({"memo": {"$regex": "^QA (YE|alert)"}}) == 0
    assert db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}}) == 0
    assert date.today().year >= 2026
