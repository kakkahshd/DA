"""
Iteration 210 - Marketing Settlements (Tahap 1) + Withdrawals (Tahap 2)
Tests the two-stage flow: platform-released -> withdrawn to bank
"""
import os
import pytest
import requests
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://dahost-staging.preview.emergentagent.com').rstrip('/')
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"

TAG = "TESTQA"
UNIQ = uuid.uuid4().hex[:6].upper()


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def store(hdr):
    """Pick Shopee GHS store, ensure coa_cash_code=1-1201."""
    r = requests.get(f"{BASE_URL}/api/marketing/accounts", headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    data = _unwrap(r.json())
    accs = data if isinstance(data, list) else data.get("items", data.get("data", []))
    target = None
    for a in accs:
        if a.get("account_name") == "Shopee GHS" or a.get("ar_account_code") == "1-1303-SHP-01":
            target = a
            break
    assert target, f"Shopee GHS not found. names={[a.get('account_name') for a in accs][:10]}"
    if not target.get("coa_cash_code"):
        r2 = requests.put(f"{BASE_URL}/api/marketing/accounts/{target['id']}",
                          headers=hdr, json={"coa_cash_code": "1-1201"}, timeout=30)
        assert r2.status_code == 200, r2.text
        target["coa_cash_code"] = "1-1201"
    return target


def _unwrap(js):
    if isinstance(js, dict) and "data" in js and ("ok" in js or "status" in js):
        return js["data"]
    return js


def _get_balance(hdr, account_id):
    r = requests.get(f"{BASE_URL}/api/marketing/settlements/platform-balance", headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    data = _unwrap(r.json())
    items = data if isinstance(data, list) else data.get("items", [])
    for it in items:
        if it.get("account_id") == account_id or it.get("receivable_code") == "1-1303-SHP-01":
            return it
    return None


# ---------- Tahap 1: Settlements ----------
class TestStage1Settlement:
    settlement_id_str = f"{TAG}-{UNIQ}-S1"
    created = {}

    def test_01_create_settlement(self, hdr, store):
        bal_before = _get_balance(hdr, store["id"]) or {}
        released_before = float(bal_before.get("released_total") or 0)
        balance_before = float(bal_before.get("balance") or 0)

        payload = {
            "settlement_id": self.settlement_id_str,
            "platform": store.get("platform") or "shopee",
            "account_id": store["id"],
            "settlement_date": "2026-06-10",
            "gross_sales": 10000000,
            "platform_commission": 1000000,
            "ads_deduction": 500000,
            "net_payout": 8500000,
            "notes": TAG,
        }
        r = requests.post(f"{BASE_URL}/api/marketing/settlements", headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        js = _unwrap(r.json())
        assert js.get("math_verified") is True, f"math_verified missing: {js}"
        TestStage1Settlement.created["id"] = js.get("id") or js.get("_id")
        TestStage1Settlement.created["released_before"] = released_before
        TestStage1Settlement.created["balance_before"] = balance_before

    def test_02_balance_released_increased(self, hdr, store):
        bal = _get_balance(hdr, store["id"])
        assert bal is not None
        released_after = float(bal.get("released_total") or 0)
        balance_after = float(bal.get("balance") or 0)
        assert round(released_after - TestStage1Settlement.created["released_before"], 2) == 8500000.0
        assert round(balance_after - TestStage1Settlement.created["balance_before"], 2) == 8500000.0

    def test_03_create_draft_journal(self, hdr):
        sid = TestStage1Settlement.created["id"]
        r = requests.post(f"{BASE_URL}/api/marketing/settlements/{sid}/journal", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        js = _unwrap(r.json())
        TestStage1Settlement.created["journal_id"] = (js.get("journal_id") or js.get("id") or (js.get("journal") or {}).get("id"))

    def test_04_journal_lines_correct(self, hdr):
        # Fetch journal via rahaza journals search by settlement_id
        jr = requests.get(f"{BASE_URL}/api/rahaza/journals",
                          headers=hdr, params={"search": TestStage1Settlement.settlement_id_str}, timeout=30)
        assert jr.status_code == 200, jr.text
        data = _unwrap(jr.json())
        entries = data if isinstance(data, list) else data.get("items", [])
        entries = [e for e in entries if e.get("source_ref") == TestStage1Settlement.settlement_id_str]
        assert entries, f"no journal for {TestStage1Settlement.settlement_id_str}"
        lines = entries[0].get("lines") or []
        assert lines, "no journal lines found"

        def sum_acct(code, side):
            return round(sum(float(l.get(side) or 0) for l in lines if l.get("account_code") == code), 2)

        assert sum_acct("1-1303-SHP-01", "debit") == 8500000.0, lines
        assert sum_acct("4-1111", "credit") == 10000000.0, lines
        assert sum_acct("4-1400", "debit") == 1000000.0, lines
        assert sum_acct("6-1112", "debit") == 500000.0, lines
        # No bank cash line
        assert not any(l.get("account_code") == "1-1201" for l in lines), f"unexpected bank line: {lines}"

    def test_05_post_journal(self, hdr, store):
        sid = TestStage1Settlement.created["id"]
        r = requests.post(f"{BASE_URL}/api/marketing/settlements/{sid}/post", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        bal = _get_balance(hdr, store["id"])
        gl = float(bal.get("gl_balance") or 0)
        TestStage1Settlement.created["gl_after_post"] = gl
        assert gl >= 8500000.0 - 1  # gl_balance increased by ~8.5m (or more if pre-existing)

    def test_06_delete_journaled_settlement_forbidden(self, hdr):
        sid = TestStage1Settlement.created["id"]
        r = requests.delete(f"{BASE_URL}/api/marketing/settlements/{sid}", headers=hdr, timeout=30)
        assert r.status_code == 400, f"expected 400 but got {r.status_code} {r.text}"


# ---------- Tahap 2: Withdrawals ----------
class TestStage2Withdrawal:
    ref1 = f"{TAG}-{UNIQ}-WD1"
    refx = f"{TAG}-{UNIQ}-WDX"
    created = {}

    def test_10_reject_exceeding_balance(self, hdr, store):
        payload = {"account_id": store["id"], "withdrawal_date": "2026-06-12",
                   "amount": 999999999, "reference": self.refx, "notes": TAG}
        r = requests.post(f"{BASE_URL}/api/marketing/withdrawals", headers=hdr, json=payload, timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text}"
        assert "saldo" in r.text.lower() or "melebihi" in r.text.lower(), r.text

    def test_11_create_ok(self, hdr, store):
        bal_before = _get_balance(hdr, store["id"])
        payload = {"account_id": store["id"], "withdrawal_date": "2026-06-12",
                   "amount": 5000000, "reference": self.ref1, "notes": TAG}
        r = requests.post(f"{BASE_URL}/api/marketing/withdrawals", headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        js = _unwrap(r.json())
        TestStage2Withdrawal.created["id"] = js.get("id") or js.get("_id")
        TestStage2Withdrawal.created["payload"] = payload
        bal_after = _get_balance(hdr, store["id"])
        assert round(float(bal_after["withdrawn_total"]) - float(bal_before["withdrawn_total"]), 2) == 5000000.0
        assert round(float(bal_before["balance"]) - float(bal_after["balance"]), 2) == 5000000.0

    def test_12_create_draft_journal(self, hdr):
        wid = TestStage2Withdrawal.created["id"]
        r = requests.post(f"{BASE_URL}/api/marketing/withdrawals/{wid}/journal", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        jr = requests.get(f"{BASE_URL}/api/rahaza/journals",
                          headers=hdr, params={"search": TestStage2Withdrawal.ref1}, timeout=30)
        assert jr.status_code == 200, jr.text
        data = _unwrap(jr.json())
        entries = data if isinstance(data, list) else data.get("items", [])
        entries = [e for e in entries if e.get("source_ref") == TestStage2Withdrawal.ref1]
        assert entries, f"no journal for {TestStage2Withdrawal.ref1}"
        lines = entries[0].get("lines") or []
        assert lines, "no wd journal lines"
        deb = sum(float(l.get("debit") or 0) for l in lines if l.get("account_code") == "1-1201")
        cre = sum(float(l.get("credit") or 0) for l in lines if l.get("account_code") == "1-1303-SHP-01")
        assert deb == 5000000.0, lines
        assert cre == 5000000.0, lines

    def test_13_idempotent_journal(self, hdr):
        wid = TestStage2Withdrawal.created["id"]
        r = requests.post(f"{BASE_URL}/api/marketing/withdrawals/{wid}/journal", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        js = _unwrap(r.json())
        assert js.get("already") is True, js

    def test_14_post_journal(self, hdr, store):
        wid = TestStage2Withdrawal.created["id"]
        bal_before = _get_balance(hdr, store["id"])
        gl_before = float(bal_before.get("gl_balance") or 0)
        r = requests.post(f"{BASE_URL}/api/marketing/withdrawals/{wid}/post", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        bal_after = _get_balance(hdr, store["id"])
        gl_after = float(bal_after.get("gl_balance") or 0)
        assert round(gl_before - gl_after, 2) == 5000000.0

    def test_15_put_exceeding_balance_forbidden(self, hdr, store):
        wid = TestStage2Withdrawal.created["id"]
        base = TestStage2Withdrawal.created["payload"]
        body = {"account_id": base["account_id"], "withdrawal_date": base["withdrawal_date"],
                "amount": 999999999, "reference": base["reference"], "notes": base.get("notes", "")}
        r = requests.put(f"{BASE_URL}/api/marketing/withdrawals/{wid}",
                         headers=hdr, json=body, timeout=30)
        assert r.status_code == 400, f"got {r.status_code} {r.text}"

    def test_16_delete_journaled_forbidden(self, hdr):
        wid = TestStage2Withdrawal.created["id"]
        r = requests.delete(f"{BASE_URL}/api/marketing/withdrawals/{wid}", headers=hdr, timeout=30)
        assert r.status_code == 400, f"got {r.status_code} {r.text}"

    def test_17_list_contains(self, hdr):
        r = requests.get(f"{BASE_URL}/api/marketing/withdrawals", headers=hdr, timeout=30)
        assert r.status_code == 200
        data = _unwrap(r.json())
        items = data if isinstance(data, list) else data.get("items", [])
        refs = [w.get("reference") for w in items]
        assert TestStage2Withdrawal.ref1 in refs, f"missing ref, sample={refs[:5]}"


# ---------- Bank recon (best-effort) ----------
class TestBankRecon:
    def test_20_sessions_endpoint_alive(self, hdr):
        r = requests.get(f"{BASE_URL}/api/finance/bank-recon/sessions", headers=hdr, timeout=30)
        assert r.status_code in (200, 204), f"got {r.status_code}: {r.text[:200]}"
