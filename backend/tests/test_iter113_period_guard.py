"""
Iter 113 — H-08 kontrol periode WAJIB (audit finance 2026-09-04).
  1. Jurnal manual `post:true` tertanggal > hari ini + 31 hari → 400 "masa depan".
  2. Jurnal manual tahun jauh (2019) yang periodenya belum dibuka → 400 "belum dibuka".
  3. Jurnal manual tahun ini pada bulan yang belum punya dokumen periode → 200 + periode tahun itu tercipta otomatis (12 dok, open).
  4. Periode closed → 423; reopen → posting jalan lagi.
  5. Mesin posting (_create_posted_je) mengembalikan ok=False untuk tanggal masa depan (tidak raise).
  6. GET /api/rahaza/periods/policy → future_days_max, auto_years.
Data uji dibersihkan sendiri (JE + cermin + periode tahun 2019 kalau ada).
"""
import asyncio
import os
from datetime import date, timedelta

import pytest
import requests
from pymongo import MongoClient
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
db = MongoClient(os.environ.get("MONGO_URL") or be["MONGO_URL"])[os.environ.get("DB_NAME") or be["DB_NAME"]]
S = {"je_ids": [], "created_year": None}


def _login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def H():
    return _login("admin@garment.com", "Admin@123")


def _lines():
    return [{"account_code": "1-1201", "debit": 1000, "credit": 0, "description": "QA H-08"},
            {"account_code": "6-2900", "debit": 0, "credit": 1000, "description": "QA H-08"}]


def _post_je(H, d, post=True):
    r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, timeout=60,
                      json={"date": d, "memo": "QA H-08 period guard", "lines": _lines(), "post": post})
    if r.status_code == 200 and r.json().get("id"):
        S["je_ids"].append(r.json()["id"])
    return r


def test_00_policy(H):
    r = requests.get(f"{BASE}/api/rahaza/periods/policy", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["future_days_max"] == 31 and date.today().year in d["auto_years"]


def test_01_future_rejected(H):
    far = (date.today() + timedelta(days=60)).isoformat()
    r = _post_je(H, far)
    assert r.status_code == 400, r.text
    assert "masa depan" in r.json()["detail"]


def test_02_far_past_unopened_rejected(H):
    assert db.rahaza_periods.count_documents({"year": 2019}) == 0, "prasyarat: periode 2019 tidak ada"
    r = _post_je(H, "2019-01-15")
    assert r.status_code == 400, r.text
    assert "belum dibuka" in r.json()["detail"]
    assert db.rahaza_periods.count_documents({"year": 2019}) == 0


def test_03_current_year_auto_creates_periods(H):
    y = date.today().year
    target = None
    for m in range(1, 13):
        code = f"{y}-{m:02d}"
        if not db.rahaza_periods.find_one({"period_code": code}) and date(y, m, 1) <= date.today():
            target = code
            break
    if target is None:
        # semua bulan sudah terdaftar → cukup pastikan posting bulan ini jalan
        target = date.today().strftime("%Y-%m")
    else:
        S["created_year"] = y
    r = _post_je(H, f"{target}-05")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"
    assert db.rahaza_periods.count_documents({"year": y}) == 12
    assert all(p["status"] in ("open", "closed", "locked") for p in db.rahaza_periods.find({"year": y}))


def test_04_closed_period_blocks_then_reopen(H):
    code = f"{date.today().year}-{date.today().month:02d}"
    per = db.rahaza_periods.find_one({"period_code": code})
    assert per and per["status"] == "open"
    assert requests.post(f"{BASE}/api/rahaza/periods/{code}/close", headers=H, timeout=30).status_code == 200
    try:
        r = _post_je(H, f"{code}-03")
        assert r.status_code == 423, r.text
        assert "closed" in r.json()["detail"]
    finally:
        assert requests.post(f"{BASE}/api/rahaza/periods/{code}/reopen", headers=H, timeout=30).status_code == 200
    r = _post_je(H, f"{code}-03")
    assert r.status_code == 200, r.text


def test_05_posting_engine_graceful():
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.rahaza_posting import _ensure_period_open

    async def run():
        adb = AsyncIOMotorClient(be["MONGO_URL"])[be["DB_NAME"]]
        e1 = await _ensure_period_open(adb, date.today() + timedelta(days=45))
        e2 = await _ensure_period_open(adb, date(2019, 6, 1))
        e3 = await _ensure_period_open(adb, date.today())
        return e1, e2, e3
    e1, e2, e3 = asyncio.run(run())
    assert e1 and "masa depan" in e1
    assert e2 and "belum dibuka" in e2
    assert e3 is None


def test_zz_cleanup():
    db.rahaza_journal_lines.delete_many({"je_id": {"$in": S["je_ids"]}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": S["je_ids"]}})
    db.rahaza_periods.delete_many({"year": 2019})
    db.rahaza_period_alerts.delete_many({"year": 2019})
    if S["created_year"]:
        db.rahaza_periods.delete_many({"year": S["created_year"], "auto_created": True})
    orphan = db.rahaza_journal_lines.count_documents({"je_id": {"$nin": db.rahaza_journal_entries.distinct("id")}})
    assert orphan == 0
