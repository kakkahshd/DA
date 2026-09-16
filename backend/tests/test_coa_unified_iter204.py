"""Iter 204 — Verifikasi CoA unified 4-digit + auto GL sync + saldo awal template/import."""
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
CODE_REGEX = re.compile(r"^\d-\d{4}$")


@pytest.fixture(scope="module")
def token():
    # cool down for rate limit
    time.sleep(2)
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@garment.com", "password": "Admin@123"},
        timeout=30,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def coa_list(headers):
    r = requests.get(f"{BASE_URL}/api/rahaza/coa/accounts", headers=headers, timeout=30)
    assert r.status_code == 200, f"GET coa: {r.status_code} {r.text[:400]}"
    data = r.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("accounts") or []
    assert items, "CoA list is empty"
    return items


class TestCoAUnified:
    def test_all_active_accounts_4digit_regex(self, coa_list):
        bad = []
        for a in coa_list:
            if a.get("is_active") is False:
                continue
            code = a.get("code") or a.get("account_code")
            if not code:
                continue
            if not CODE_REGEX.match(code):
                bad.append(code)
        assert not bad, f"Non 4-digit codes among active accounts: {bad[:20]}"

    def test_no_legacy_3digit_codes(self, coa_list):
        legacy = [a for a in coa_list if re.match(r"^\d-\d{3}$", (a.get("code") or ""))]
        assert not legacy, f"Legacy 3-digit codes present: {[a.get('code') for a in legacy][:10]}"

    def test_specific_required_accounts(self, coa_list):
        by_code = {(a.get("code") or a.get("account_code")): a for a in coa_list}
        required = {
            "1-1211": "Bank BCA",
            "1-1251": "GoPay",
            "4-1111": "Shopee Grosirhijabsragen",
            "5-4200": "Biaya Vendor CMT",
            "2-1110": "Hutang Vendor CMT",
        }
        missing = []
        wrong_name = []
        for code, name_frag in required.items():
            acc = by_code.get(code)
            if not acc:
                missing.append(code)
                continue
            nm = (acc.get("name") or acc.get("account_name") or "").lower()
            if name_frag.lower() not in nm:
                wrong_name.append((code, acc.get("name") or acc.get("account_name")))
        assert not missing, f"Missing required accounts: {missing}"
        assert not wrong_name, f"Wrong name mapping: {wrong_name}"


class TestJournalPosting:
    created_journal_id = None

    def test_post_manual_balanced_journal(self, headers):
        payload = {
            "date": "2026-01-15",
            "memo": "UJI QA coa",
            "source_module": "manual",
            "post": True,
            "lines": [
                {"account_code": "1-1101", "account_name": "Kas Kecil",
                 "account_type": "ASSET", "debit": 10000, "credit": 0},
                {"account_code": "3-1000", "account_name": "Modal Disetor",
                 "account_type": "EQUITY", "debit": 0, "credit": 10000},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals", json=payload,
                          headers=headers, timeout=30)
        assert r.status_code in (200, 201), f"Post journal: {r.status_code} {r.text[:400]}"
        data = r.json()
        jid = data.get("id") or data.get("_id") or (data.get("journal") or {}).get("id")
        assert jid, f"No journal id returned: {data}"
        TestJournalPosting.created_journal_id = jid

    def test_reject_header_account(self, headers):
        payload = {
            "date": "2026-01-15",
            "memo": "UJI QA coa header",
            "source_module": "manual",
            "post": True,
            "lines": [
                {"account_code": "1-1200", "account_name": "Header Bank",
                 "account_type": "ASSET", "debit": 5000, "credit": 0},
                {"account_code": "3-1000", "account_name": "Modal Disetor",
                 "account_type": "EQUITY", "debit": 0, "credit": 5000},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals", json=payload,
                          headers=headers, timeout=30)
        assert r.status_code >= 400, f"Header 1-1200 should be rejected, got {r.status_code}: {r.text[:200]}"

    def test_reject_legacy_3digit_code(self, headers):
        payload = {
            "date": "2026-01-15",
            "memo": "UJI QA coa 3digit",
            "source_module": "manual",
            "post": True,
            "lines": [
                {"account_code": "1-110", "account_name": "Kas Legacy",
                 "account_type": "ASSET", "debit": 1000, "credit": 0},
                {"account_code": "3-1000", "account_name": "Modal Disetor",
                 "account_type": "EQUITY", "debit": 0, "credit": 1000},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals", json=payload,
                          headers=headers, timeout=30)
        assert r.status_code >= 400, f"Legacy 1-110 should be rejected, got {r.status_code}"

    def test_zzz_cleanup_void_journal(self, headers):
        jid = TestJournalPosting.created_journal_id
        if not jid:
            pytest.skip("No journal created to void")
        r = requests.post(f"{BASE_URL}/api/rahaza/journals/{jid}/void",
                          headers=headers, timeout=30)
        assert r.status_code in (200, 204), f"Void: {r.status_code} {r.text[:200]}"


class TestPostingProfilesChannelMap:
    def test_posting_profiles_use_valid_non_header(self, headers, coa_list):
        r = requests.get(f"{BASE_URL}/api/rahaza/posting-profiles",
                         headers=headers, timeout=30)
        assert r.status_code == 200, f"posting-profiles: {r.status_code} {r.text[:200]}"
        data = r.json()
        profiles = data if isinstance(data, list) else data.get("items") or data.get("profiles") or []
        by_code = {(a.get("code") or a.get("account_code")): a for a in coa_list}
        bad = []
        # walk all string values that look like account code
        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{path}[{i}]")
            elif isinstance(obj, str) and re.match(r"^\d-\d{3,4}$", obj):
                if not CODE_REGEX.match(obj):
                    bad.append((path, obj, "not_4digit"))
                elif obj not in by_code:
                    bad.append((path, obj, "not_in_coa"))
                else:
                    acc = by_code[obj]
                    if acc.get("is_header") or acc.get("is_parent"):
                        bad.append((path, obj, "header"))
        walk(profiles)
        assert not bad, f"Posting profiles have invalid account codes: {bad[:20]}"

    def test_channel_gl_mapping_all_4digit(self, headers):
        r = requests.get(f"{BASE_URL}/api/rahaza/channel-gl-mapping",
                         headers=headers, timeout=30)
        assert r.status_code == 200, f"channel-gl: {r.status_code} {r.text[:200]}"
        data = r.json()
        text = str(data)
        legacy = re.findall(r"\"\d-\d{3}\"", text)
        assert not legacy, f"channel-gl-mapping still has 3-digit codes: {set(legacy)}"


class TestModelsCategories:
    def test_all_models_have_category(self, headers):
        r = requests.get(f"{BASE_URL}/api/rahaza/models", headers=headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        models = data if isinstance(data, list) else data.get("items") or data.get("models") or []
        assert len(models) >= 100, f"Expected ~104 models, got {len(models)}"
        no_cat = [m for m in models if not (m.get("category_id") or m.get("categoryId"))]
        assert not no_cat, f"{len(no_cat)} models without category_id (sample: {[m.get('code') or m.get('model_code') for m in no_cat[:5]]})"

    def test_product_categories_has_expected(self, headers):
        r = requests.get(f"{BASE_URL}/api/rahaza/product-categories",
                         headers=headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        cats = data if isinstance(data, list) else data.get("items") or data.get("categories") or []
        names = {(c.get("name") or c.get("category_name") or "").lower() for c in cats}
        expected = {"top", "one set", "inner", "tunik", "dress", "blouse", "celana"}
        missing = expected - names
        assert not missing, f"Missing categories: {missing}. Have: {names}"
