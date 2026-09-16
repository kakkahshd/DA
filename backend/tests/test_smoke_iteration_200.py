"""Smoke test suite for iteration 200 — verify preview setup after master data import."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dahost-staging.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASSWORD = "Admin@123"
IMPORT_USER_EMAIL = "tanti.n@dewiaditya.id"
IMPORT_USER_PASSWORD = "Dewi@123"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:300]}"
    token = r.json().get("token") or r.json().get("access_token")
    assert token, f"No token in login response: {r.json()}"
    return token


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# --- 1) Health check ---
def test_health(session):
    r = session.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200, f"health status={r.status_code} body={r.text[:300]}"
    body = r.json()
    # accept common keys
    status_ok = str(body.get("status", "")).lower() in ("ok", "healthy", "up") or body.get("ok") is True
    assert status_ok, f"health status not ok: {body}"
    db_field = body.get("db") or body.get("database") or body.get("mongo") or {}
    # accept 'connected' str or bool True
    db_connected = (
        db_field is True
        or (isinstance(db_field, str) and db_field.lower() in ("connected", "ok", "up"))
        or (isinstance(db_field, dict) and (db_field.get("connected") is True or str(db_field.get("status", "")).lower() in ("ok", "connected")))
    )
    assert db_connected, f"db not connected: {body}"


# --- 2) Admin login ---
def test_admin_login(admin_token):
    assert admin_token and len(admin_token) > 10


# --- 3) Master data counts ---
def test_locations_11(session, admin_headers):
    r = session.get(f"{BASE_URL}/api/rahaza/locations", headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"locations status={r.status_code} body={r.text[:400]}"
    data = r.json()
    items = data if isinstance(data, list) else (data.get("items") or data.get("data") or data.get("results") or [])
    total = data.get("total") if isinstance(data, dict) else None
    count = total if total is not None else len(items)
    assert count == 11, f"expected 11 locations got {count}; sample: {items[:3] if items else data}"
    codes = {(it.get("kode") or it.get("code")) for it in items}
    for expected in ("GD-L1-RAK", "GD-L1-ACC", "GD-L1-QC", "GD-L2-CUT", "GD-L2"):
        assert expected in codes, f"missing location code {expected} in {codes}"


def test_models_104(session, admin_headers):
    r = session.get(f"{BASE_URL}/api/rahaza/models", headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"models status={r.status_code} body={r.text[:400]}"
    data = r.json()
    items = data if isinstance(data, list) else (data.get("items") or data.get("data") or data.get("results") or [])
    total = data.get("total") if isinstance(data, dict) else None
    count = total if total is not None else len(items)
    assert count == 104, f"expected 104 models got {count}"


def test_employees_50(session, admin_headers):
    r = session.get(f"{BASE_URL}/api/rahaza/employees", headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"employees status={r.status_code} body={r.text[:400]}"
    data = r.json()
    total = data.get("total") if isinstance(data, dict) else None
    if total is None:
        items = data if isinstance(data, list) else (data.get("items") or data.get("data") or data.get("results") or [])
        total = len(items)
    assert total == 50, f"expected 50 employees got {total}; keys={list(data.keys()) if isinstance(data, dict) else 'list'}"


def test_users_27(session, admin_headers):
    r = session.get(f"{BASE_URL}/api/users", headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"users status={r.status_code} body={r.text[:400]}"
    data = r.json()
    items = data if isinstance(data, list) else (data.get("items") or data.get("data") or data.get("results") or [])
    total = data.get("total") if isinstance(data, dict) else len(items)
    assert total == 27, f"expected 27 users got {total}"


# --- 4) Import account first login with must_change_password ---
def test_import_user_login_must_change_password(session):
    r = session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": IMPORT_USER_EMAIL, "password": IMPORT_USER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"import user login failed: {r.status_code} {r.text[:400]}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    assert token, f"no token: {body}"
    # Check flag in login response OR /api/auth/me
    mcp_in_login = body.get("must_change_password") is True or (isinstance(body.get("user"), dict) and body["user"].get("must_change_password") is True)
    if not mcp_in_login:
        me = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        assert me.status_code == 200, f"/api/auth/me failed: {me.status_code} {me.text[:300]}"
        mb = me.json()
        assert mb.get("must_change_password") is True, f"must_change_password not true: login={body} me={mb}"


# --- 6) Seed demo endpoint must be 403 ---
def test_seed_demo_forbidden(session, admin_headers):
    r = session.post(f"{BASE_URL}/api/seed/maklon-full", headers=admin_headers, json={}, timeout=30)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:400]}"
