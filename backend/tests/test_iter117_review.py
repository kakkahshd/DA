"""Iteration 117 review tests: RBAC, cron secrets, PO cost-check, sales flow end-to-end."""
import os
import uuid
import requests
import pytest
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"
SECRET = os.environ.get("WEBHOOK_CRON_SECRET", "")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@garment.com", "Admin@123")


@pytest.fixture(scope="module")
def hr_tok():
    return _login("hr@dewiaditya.id", "Dewi@123")


@pytest.fixture(scope="module")
def gudang_tok():
    return _login("gudang@dewiaditya.id", "Dewi@123")


# ---------- RBAC ----------
def test_rbac_hr_forbidden_sales(hr_tok):
    r = requests.get(f"{API}/sales/fg-stock", headers={"Authorization": f"Bearer {hr_tok}"}, timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code}"


def test_rbac_gudang_allowed_sales(gudang_tok):
    r = requests.get(f"{API}/sales/fg-stock", headers={"Authorization": f"Bearer {gudang_tok}"}, timeout=15)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"


def test_rbac_admin_allowed_sales(admin_tok):
    r = requests.get(f"{API}/sales/fg-stock", headers={"Authorization": f"Bearer {admin_tok}"}, timeout=15)
    assert r.status_code == 200


# ---------- Cron mark-overdue ----------
def test_cron_mark_overdue_no_auth():
    r = requests.post(f"{API}/cron/mark-overdue", timeout=15)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_cron_mark_overdue_accepted_and_duplicate():
    wid = f"test-review-{uuid.uuid4().hex[:12]}"
    h = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": wid}
    r1 = requests.post(f"{API}/cron/mark-overdue", headers=h, timeout=30)
    assert r1.status_code == 200, r1.text[:300]
    assert r1.json().get("status") == "accepted"
    r2 = requests.post(f"{API}/cron/mark-overdue", headers=h, timeout=30)
    assert r2.status_code == 200
    assert r2.json().get("status") == "duplicate"


# ---------- Cron fg-valuation-check ----------
def test_cron_fg_valuation_check_secret():
    wid = f"test-review-{uuid.uuid4().hex[:12]}"
    h = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": wid}
    r = requests.post(f"{API}/cron/fg-valuation-check", headers=h, timeout=30)
    assert r.status_code == 200
    assert r.json().get("status") == "accepted"


def test_cron_fg_valuation_run_now_admin(admin_tok):
    r = requests.post(
        f"{API}/cron/fg-valuation-check/run-now",
        headers={"Authorization": f"Bearer {admin_tok}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    assert "result" in j
    res = j["result"]
    assert set(["difference", "unexplained_difference", "explained", "notified"]).issubset(res.keys())


# ---------- Production PO cost-check ----------
def test_production_po_cost_check(admin_tok):
    h = {"Authorization": f"Bearer {admin_tok}"}
    r = requests.get(f"{API}/production-pos?business_type=internal", headers=h, timeout=20)
    assert r.status_code == 200
    pos = r.json()
    if isinstance(pos, dict):
        pos = pos.get("items") or pos.get("data") or []
    if not pos:
        pytest.skip("no internal PO found")
    po = pos[0]
    po_id = po.get("id") or po.get("_id") or po.get("po_id")
    assert po_id, f"no id in po: {list(po.keys())}"
    r2 = requests.get(f"{API}/production-pos/{po_id}/cost-check", headers=h, timeout=20)
    assert r2.status_code == 200, r2.text[:300]
    j = r2.json()
    assert "items" in j
    assert "items_with_issues" in j
    assert "ok" in j
