"""QA iter206 — Sinkronisasi Bagan Akun (CoA) dengan Kas & Bank, Auto Akun, Peta Channel, Toko."""
from __future__ import annotations

import os
import time
import re

import pytest
import requests


def _load_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


URL = _load_url().rstrip("/")
BASE = URL + "/api"


def _login() -> str:
    for _ in range(5):
        r = requests.post(f"{BASE}/auth/login", json={"email": "admin@garment.com", "password": "Admin@123"}, timeout=30)
        if r.status_code == 200:
            return r.json()["token"]
        time.sleep(3)
    pytest.skip(f"login gagal: {r.status_code} {r.text[:200]}")


@pytest.fixture(scope="module")
def H():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture(scope="module")
def db():
    from pymongo import MongoClient
    cli = MongoClient(os.environ.get("MONGO_URL") or "mongodb://localhost:27017")
    return cli[os.environ.get("DB_NAME") or "test_database"]


EXPECTED_GL = {
    "1-1101", "1-1102",
    "1-1201", "1-1202",
    "1-1211", "1-1212", "1-1213", "1-1214", "1-1215", "1-1219",
    "1-1221", "1-1222", "1-1223", "1-1224", "1-1225",
    "1-1251", "1-1252", "1-1253", "1-1254", "1-1255",
}


class TestCashAccounts:
    def test_list_20_all_linked(self, H):
        r = requests.get(f"{BASE}/rahaza/cash-accounts", headers=H, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("accounts") or data.get("items") or data.get("data") or []
        assert isinstance(rows, list), f"unexpected shape: {type(data)} {str(data)[:200]}"
        # semua rows harus punya gl_account_code == code (yang berupa 1-1xxx)
        codes = {r.get("gl_account_code") for r in rows if r.get("gl_account_code")}
        missing = EXPECTED_GL - codes
        assert not missing, f"missing gl_account_code: {sorted(missing)}"
        # balance_source == 'gl'
        for row in rows:
            gl = row.get("gl_account_code")
            if gl in EXPECTED_GL:
                assert row.get("balance_source") == "gl", f"{gl} balance_source={row.get('balance_source')}"

    def test_gl_candidates_empty(self, H):
        r = requests.get(f"{BASE}/rahaza/cash-accounts/gl-candidates", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("candidates") or data.get("items") or []
        assert rows == [] or len(rows) == 0, f"expected empty, got {rows}"

    def test_create_conflict_and_bad_gl(self, H):
        # Kode gl sudah tertaut → 409
        r = requests.post(f"{BASE}/rahaza/cash-accounts", json={"code": "QA-F49", "name": "QA", "type": "bank", "gl_account_code": "1-1211"}, headers=H, timeout=15)
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:200]}"
        # gl_account_code bukan cash/bank/wallet → 400
        r2 = requests.post(f"{BASE}/rahaza/cash-accounts", json={"code": "QA-F49", "name": "QA", "type": "bank", "gl_account_code": "4-1100"}, headers=H, timeout=15)
        assert r2.status_code == 400, f"expected 400, got {r2.status_code} {r2.text[:200]}"

    def test_create_new_with_auto_gl_and_cleanup(self, H, db):
        # buat rekening bank baru tanpa gl → generate CoA 1-1200-…
        payload = {"code": "QA-F49-NEW", "name": "QA Bank Baru", "type": "bank"}
        r = requests.post(f"{BASE}/rahaza/cash-accounts", json=payload, headers=H, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        cash_id = j.get("id") or (j.get("account") or {}).get("id")
        gl_code = j.get("gl_account_code") or (j.get("account") or {}).get("gl_account_code")
        assert gl_code and gl_code.startswith("1-1200-"), f"gl_code={gl_code}"
        assert cash_id
        try:
            # verifikasi ada di CoA
            coa = requests.get(f"{BASE}/rahaza/coa/accounts", headers=H, timeout=30).json()
            accs = coa if isinstance(coa, list) else coa.get("accounts", [])
            assert any(a.get("code") == gl_code for a in accs), f"CoA missing {gl_code}"
        finally:
            # cleanup rekening
            requests.delete(f"{BASE}/rahaza/cash-accounts/{cash_id}", headers=H, timeout=15)
            # cleanup CoA
            db.rahaza_coa_accounts.delete_many({"code": {"$regex": r"^1-1[12]00-QA"}})

    def test_create_cash_type_subledger_under_1_1100(self, H, db):
        # type=cash tanpa gl → sub-ledger di 1-1100
        payload = {"code": "QA-F49-CASH", "name": "QA Kas Baru", "type": "cash"}
        r = requests.post(f"{BASE}/rahaza/cash-accounts", json=payload, headers=H, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        cash_id = j.get("id") or (j.get("account") or {}).get("id")
        gl_code = j.get("gl_account_code") or (j.get("account") or {}).get("gl_account_code")
        assert gl_code and gl_code.startswith("1-1100-"), f"gl_code={gl_code}"
        try:
            coa = requests.get(f"{BASE}/rahaza/coa/accounts", headers=H, timeout=30).json()
            accs = coa if isinstance(coa, list) else coa.get("accounts", [])
            new_acc = next((a for a in accs if a.get("code") == gl_code), None)
            assert new_acc, f"CoA missing {gl_code}"
            assert new_acc.get("parent_code") == "1-1100", f"parent={new_acc.get('parent_code')}"
        finally:
            requests.delete(f"{BASE}/rahaza/cash-accounts/{cash_id}", headers=H, timeout=15)
            db.rahaza_coa_accounts.delete_many({"code": {"$regex": r"^1-1[12]00-QA"}})


class TestSyncMasters:
    def test_idempotent(self, H):
        r1 = requests.post(f"{BASE}/rahaza/finance/sync-masters", headers=H, timeout=60)
        assert r1.status_code == 200, r1.text
        # kedua run: nihil created
        r2 = requests.post(f"{BASE}/rahaza/finance/sync-masters", headers=H, timeout=60)
        assert r2.status_code == 200, r2.text
        j = r2.json()
        # Fleksibel shape:
        # look for cash_accounts_created empty & stores.revenue_created empty & subledgers_created 0
        s = str(j)
        # Extract cash_accounts_created
        cash = j.get("cash_accounts_created", j.get("cash_accounts", {}).get("created") if isinstance(j.get("cash_accounts"), dict) else None)
        stores = j.get("stores", {})
        rev = stores.get("revenue_created") if isinstance(stores, dict) else None
        subs = j.get("subledgers_created")
        # If any counters exist, must be 0/[]
        empties = []
        if isinstance(cash, list): empties.append(("cash_accounts_created", cash))
        if isinstance(rev, list): empties.append(("stores.revenue_created", rev))
        if isinstance(subs, dict):
            for k, v in subs.items():
                empties.append((f"subledgers_created.{k}", v))
        for name, val in empties:
            assert not val, f"{name} not empty on 2nd run: {val}"
        print(f"SYNC RESULT R2: {j}")


class TestCoAAutoSettings:
    def test_settings(self, H):
        r = requests.get(f"{BASE}/rahaza/coa-auto/settings", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        et = j.get("entity_types") or j.get("settings", {}).get("entity_types") or {}
        cmt = et.get("cmt_vendor")
        assert cmt, f"cmt_vendor missing. keys={list(et.keys())}"
        assert cmt.get("collection") == "vendor_partners", cmt
        assert cmt.get("parent_code") == "2-1110", cmt
        mk = et.get("maklon_client")
        assert mk, f"maklon_client missing. keys={list(et.keys())}"
        assert mk.get("parent_code") == "1-1305", mk


class TestCoAAccounts:
    def test_subledgers_and_store_revenue(self, H):
        r = requests.get(f"{BASE}/rahaza/coa/accounts", params={"active_only": "false"}, headers=H, timeout=30)
        assert r.status_code == 200
        data = r.json()
        accs = data if isinstance(data, list) else data.get("accounts", [])
        codes = {a["code"]: a for a in accs}
        # 10 vendor 2-1110-*
        vendors = [c for c in codes if re.match(r"^2-1110-", c)]
        assert len(vendors) >= 10, f"vendors: {len(vendors)}"
        # 1 klien 1-1305-*
        clients = [c for c in codes if re.match(r"^1-1305-", c)]
        assert len(clients) >= 1, f"clients: {len(clients)}"
        # 7 toko 1-1303-*
        stores_ar = [c for c in codes if re.match(r"^1-1303-", c)]
        assert len(stores_ar) >= 7, f"stores_ar: {len(stores_ar)}"
        # revenue aktif
        for code in ("4-1115", "4-1116", "4-1117", "4-1127"):
            a = codes.get(code)
            assert a and a.get("active") is True, f"{code} missing/inactive: {a}"
        # revenue nonaktif
        for code in ("4-1112", "4-1113", "4-1123", "4-1124", "4-1125", "4-1131"):
            a = codes.get(code)
            assert a and a.get("active") is False, f"{code} not inactive: {a}"


class TestChannelAndPostingProfiles:
    def test_channel_gl_mapping(self, H):
        r = requests.get(f"{BASE}/rahaza/channel-gl-mapping", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("mappings") or data.get("items") or []
        active = [x for x in rows if x.get("active", True)]
        keys = {x.get("channel_key") for x in active}
        expected = {"SHP-01", "SHP-02", "SHP-03", "SHP-04", "TTK-01", "TTK-02", "TTK-03"}
        assert expected <= keys, f"missing: {expected - keys}"
        for x in active:
            if x.get("channel_key") in expected:
                assert (x.get("credit_revenue") or "").startswith("4-11"), x
                dar = x.get("debit_ar") or ""
                assert dar.startswith("1-1303-"), x

    def test_posting_profile_cmt_ap(self, H):
        r = requests.get(f"{BASE}/rahaza/posting-profiles", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("profiles") or data.get("items") or []
        row = next((x for x in rows if x.get("event_type") == "cmt_ap_invoice"), None)
        assert row, f"cmt_ap_invoice not found. events={[x.get('event_type') for x in rows]}"
        mapping = row.get("mapping") or row.get("accounts") or {}
        assert mapping.get("credit_ap") == "2-1110", f"credit_ap={mapping.get('credit_ap')}"


class TestRegression:
    def test_trial_balance(self, H):
        r = requests.get(f"{BASE}/rahaza/finance/reports/trial-balance", params={"from": "2026-01-01", "to": "2026-12-31"}, headers=H, timeout=30)
        assert r.status_code == 200, r.text
