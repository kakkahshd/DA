"""Iter 201 — Kode pelanggan lewat kebijakan penomoran & blocked_location_ids karantina."""
import os
import re
import asyncio
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN = {"email": "admin@garment.com", "password": "Admin@123"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    # Final cleanup: remove any UJI QA customers and unset mode
    db = c[DB_NAME]
    db.rahaza_customers.delete_many({"name": {"$regex": "^UJI QA"}})
    db.rahaza_coa_accounts.delete_many({"name": {"$regex": "UJI QA"}})
    db.doc_number_configs.update_one({"key": "rahaza_customers.code"}, {"$unset": {"mode": ""}})
    c.close()


# ── 1. GET doc-number-policy default (auto) ──────────────────────────────────
def test_policy_default_auto(h):
    r = requests.get(f"{BASE_URL}/api/doc-number-policy?key=rahaza_customers.code", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "auto", d
    assert d["format"] == "CUST-{SEQ:4}", d
    assert re.match(r"^CUST-\d{4}$", d["contoh"]), d


# ── 2. POST tanpa code di mode auto → sukses CUST-XXXX ───────────────────────
def test_create_customer_auto_success(h, mdb):
    # Cleanup up-front
    mdb.rahaza_customers.delete_many({"name": {"$regex": "^UJI QA"}})
    r = requests.post(f"{BASE_URL}/api/sales/customers", headers=h,
                      json={"name": "UJI QA Pelanggan"}, timeout=30)
    assert r.status_code in (200, 201), r.text
    d = r.json()
    assert re.match(r"^CUST-\d{4}$", d["code"]), d
    assert d["name"] == "UJI QA Pelanggan"
    # Verify persistence
    doc = mdb.rahaza_customers.find_one({"id": d["id"]})
    assert doc is not None
    assert doc["code"] == d["code"]


# ── 3. POST dengan code di mode auto → 400 pesan 'OTOMATIS' ─────────────────
def test_create_customer_auto_reject_manual_code(h):
    r = requests.post(f"{BASE_URL}/api/sales/customers", headers=h,
                      json={"name": "UJI QA 2", "code": "BEBAS-1"}, timeout=30)
    assert r.status_code == 400, r.text
    assert "OTOMATIS" in r.text.upper()


# ── 4. Switch mode to manual, test manual behavior ───────────────────────────
def test_manual_mode_flow(h, mdb):
    # Set mode manual
    r = requests.put(f"{BASE_URL}/api/admin/doc-numbering", headers=h,
                     json={"key": "rahaza_customers.code", "mode": "manual", "active": True}, timeout=30)
    assert r.status_code == 200, r.text

    try:
        # No code → 400 (wajib)
        r = requests.post(f"{BASE_URL}/api/sales/customers", headers=h,
                          json={"name": "UJI QA Manual Kosong"}, timeout=30)
        assert r.status_code == 400, r.text
        assert "wajib" in r.text.lower() or "MANUAL" in r.text.upper()

        # Invalid pattern → 400
        r = requests.post(f"{BASE_URL}/api/sales/customers", headers=h,
                          json={"name": "UJI QA Manual ABC", "code": "ABC"}, timeout=30)
        assert r.status_code == 400, r.text
        assert "pola" in r.text.lower() or "tidak mengikuti" in r.text.lower()

        # Valid code CUST-9901 → 201
        r = requests.post(f"{BASE_URL}/api/sales/customers", headers=h,
                          json={"name": "UJI QA Manual OK", "code": "CUST-9901"}, timeout=30)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        assert d["code"] == "CUST-9901"
    finally:
        # Restore mode
        requests.put(f"{BASE_URL}/api/admin/doc-numbering", headers=h,
                     json={"key": "rahaza_customers.code", "mode": "auto", "active": True}, timeout=30)
        mdb.doc_number_configs.update_one(
            {"key": "rahaza_customers.code"}, {"$unset": {"mode": ""}})
        # Cleanup test customers
        mdb.rahaza_customers.delete_many({"name": {"$regex": "^UJI QA"}})
        mdb.rahaza_coa_accounts.delete_many({"name": {"$regex": "UJI QA"}})


# ── 5. blocked_location_ids includes QC role but not FG rack ─────────────────
def test_blocked_location_ids_includes_karantina(mdb):
    qc = mdb.rahaza_locations.find_one({"code": "GD-L1-QC"})
    fg = mdb.rahaza_locations.find_one({"code": "GD-L1-RAK"})
    assert qc is not None, "Lokasi GD-L1-QC harus ada"
    assert fg is not None, "Lokasi GD-L1-RAK harus ada"

    # Panggil core.catalog_stock.blocked_location_ids langsung
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        from core import catalog_stock as cs
        ids = await cs.blocked_location_ids(db)
        cli.close()
        return ids

    ids = asyncio.run(run())
    assert qc["id"] in ids, f"Lokasi karantina GD-L1-QC ({qc['id']}) harus terblokir; storage_role={qc.get('storage_role')}, role={qc.get('role')}"
    assert fg["id"] not in ids, f"Lokasi FG GD-L1-RAK ({fg['id']}) tidak boleh terblokir"


# ── 6. Final cleanup verification (no UJI QA rows left) ──────────────────────
def test_cleanup_no_residual(mdb):
    residual = list(mdb.rahaza_customers.find({"name": {"$regex": "^UJI QA"}}))
    # Cleanup if any left
    if residual:
        mdb.rahaza_customers.delete_many({"name": {"$regex": "^UJI QA"}})
    mdb.rahaza_coa_accounts.delete_many({"name": {"$regex": "UJI QA"}})
    # Ensure mode reset
    cfg = mdb.doc_number_configs.find_one({"key": "rahaza_customers.code"}) or {}
    assert "mode" not in cfg, f"Mode harus di-unset di akhir, tersisa: {cfg.get('mode')}"
