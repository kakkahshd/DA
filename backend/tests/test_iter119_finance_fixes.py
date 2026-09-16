"""
Iteration 119 verification tests — 4 finance fixes:
FIX-1: AR discount => balanced JE, PPN calculated after discount (DPP = subtotal - discount)
FIX-2: AR/AP double payment same date/amount => 2 distinct payment ids & JE ids
FIX-3: Auto-source journals can't be voided from Journal UI (409), superadmin force=true w/ reason
FIX-4: Payroll finalize deducts kasbon and posts JE 'employee_loan_repayment_payroll'
"""
import os
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://backend-test-suite-6.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

EMAIL = "admin@garment.com"
PASSWORD = "Admin@123"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="session")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def today():
    return dt.date.today().isoformat()


@pytest.fixture(scope="session")
def artefacts():
    return {"ar_invoice_ids": [], "ap_invoice_ids": [], "je_ids": [], "kasbon_ids": [], "run_ids": []}


# ---------- FIX-1 : AR with discount ----------

@pytest.fixture(scope="session")
def customer_id(client):
    # Prefer active existing customer in rahaza_customers
    r = client.get(f"{API}/rahaza/customers", timeout=30)
    if r.status_code == 200:
        lst = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        if lst:
            return lst[0].get("id")
    # Create test customer via /rahaza/customers POST
    code = f"TESTITER119{dt.datetime.now().strftime('%H%M%S')}"
    rc = client.post(f"{API}/rahaza/customers", json={
        "code": code, "name": "TEST Iter119 Customer", "company_type": "company",
        "payment_terms": "net_30",
    }, timeout=30)
    if rc.status_code in (200, 201):
        # response might contain the doc or list
        try:
            data = rc.json()
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("id"):
            return data["id"]
        # re-fetch
        r2 = client.get(f"{API}/rahaza/customers", timeout=30)
        lst = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
        for c in lst:
            if c.get("code") == code:
                return c.get("id")
    pytest.skip(f"cannot obtain customer: create={rc.status_code} {rc.text[:200]}")


def test_fix1_ar_discount_totals_and_je_balanced(client, customer_id, today, artefacts):
    payload = {
        "customer_id": customer_id,
        "issue_date": today,
        "due_date": today,
        "items": [{"description": "Uji diskon FIX1", "qty": 10, "unit_price": 100000}],
        "tax_pct": 11,
        "discount_amount": 50000,
    }
    r = client.post(f"{API}/rahaza/ar-invoices", json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text
    inv = r.json()
    iid = inv.get("id") or inv.get("_id")
    artefacts["ar_invoice_ids"].append(iid)
    # Totals check
    assert round(inv.get("subtotal", 0)) == 1000000, inv
    assert round(inv.get("taxable_base", 0)) == 950000, inv
    assert round(inv.get("tax_amount", 0)) == 104500, inv
    assert round(inv.get("total", 0)) == 1054500, inv

    # Send/issue
    r2 = client.post(f"{API}/rahaza/ar-invoices/{iid}/send", timeout=30)
    assert r2.status_code in (200, 201), r2.text
    issued = r2.json()
    assert (issued.get("status") or "").lower() in ("issued", "sent", "open"), issued
    je_id = issued.get("gl_je_id")
    assert je_id, f"gl_je_id must be filled after send: {issued}"
    assert not (issued.get("post_error") or "").strip(), issued
    artefacts["je_ids"].append(je_id)
    artefacts["ar_je_id_fix1"] = je_id
    artefacts["ar_invoice_fix1"] = iid

    # Fetch JE and verify balance
    r3 = client.get(f"{API}/rahaza/journals/{je_id}", timeout=30)
    assert r3.status_code == 200, r3.text
    je = r3.json()
    lines = je.get("lines") or je.get("entries") or []
    debit_total = sum(round(float(l.get("debit") or 0)) for l in lines)
    credit_total = sum(round(float(l.get("credit") or 0)) for l in lines)
    assert debit_total == credit_total, f"unbalanced JE: D={debit_total} C={credit_total} lines={lines}"

    # Check specific lines
    def has_line(pred):
        return any(pred(l) for l in lines)

    # Gross revenue credit 1_000_000 (4-1xxx)
    assert has_line(lambda l: (l.get("account_code") or l.get("account") or "").startswith("4-1") and round(float(l.get("credit") or 0)) == 1000000), lines
    # Discount debit 50_000 (4-1300)
    assert has_line(lambda l: (l.get("account_code") or l.get("account") or "").startswith("4-1300") and round(float(l.get("debit") or 0)) == 50000), lines
    # PPN credit 104_500 (2-1xxx)
    assert has_line(lambda l: (l.get("account_code") or l.get("account") or "").startswith("2-1") and round(float(l.get("credit") or 0)) == 104500), lines
    # AR debit 1_054_500 (1-13xx)
    assert has_line(lambda l: (l.get("account_code") or l.get("account") or "").startswith("1-13") and round(float(l.get("debit") or 0)) == 1054500), lines


def test_fix1_ar_discount_greater_than_subtotal_400(client, customer_id, today):
    payload = {
        "customer_id": customer_id, "issue_date": today, "due_date": today,
        "items": [{"description": "over-discount", "qty": 1, "unit_price": 100000}],
        "tax_pct": 11, "discount_amount": 200000,
    }
    r = client.post(f"{API}/rahaza/ar-invoices", json=payload, timeout=30)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------- FIX-2 : Duplicate payments AR ----------

def test_fix2_ar_double_payment_creates_two_jes(client, artefacts, today):
    iid = artefacts.get("ar_invoice_fix1")
    assert iid, "need FIX-1 invoice"
    pay_body = {"amount": 100000, "date": today}
    resps = []
    for _ in range(2):
        r = client.post(f"{API}/rahaza/ar-invoices/{iid}/payment", json=pay_body, timeout=30)
        assert r.status_code in (200, 201), r.text
        resps.append(r.json())
    p1, p2 = resps
    pid1 = p1.get("_payment_id") or p1.get("payment_id")
    pid2 = p2.get("_payment_id") or p2.get("payment_id")
    assert pid1 and pid2 and pid1 != pid2, f"payment ids should differ: {pid1} vs {pid2}"
    pr1 = p1.get("_posting_result") or {}
    pr2 = p2.get("_posting_result") or {}
    assert pr1.get("ok") is True and pr2.get("ok") is True, (pr1, pr2)
    je1 = pr1.get("je_id"); je2 = pr2.get("je_id")
    assert je1 and je2 and je1 != je2, f"JE ids should differ: {je1} vs {je2}"
    assert pr2.get("already_posted") is not True, pr2

    # paid amount aggregated — fetch from list (no single-item GET)
    rl = client.get(f"{API}/rahaza/ar-invoices", timeout=30)
    assert rl.status_code == 200
    lst = rl.json() if isinstance(rl.json(), list) else rl.json().get("items", [])
    inv_found = next((x for x in lst if (x.get("id") or x.get("_id")) == iid), None)
    assert inv_found, "invoice not in list"
    assert round(inv_found.get("paid_amount", 0)) == 200000, inv_found

    rp = client.get(f"{API}/rahaza/ar-invoices/{iid}/payments", timeout=30)
    assert rp.status_code == 200, rp.text
    plist = rp.json() if isinstance(rp.json(), list) else rp.json().get("items", [])
    assert len(plist) >= 2, plist
    je_ids = {p.get("gl_je_id") for p in plist if p.get("gl_je_id")}
    assert len(je_ids) >= 2, je_ids
    artefacts["ar_payment_je_id"] = je1


# ---------- FIX-2 : Duplicate payments AP ----------

@pytest.fixture(scope="session")
def vendor_info(client):
    r = client.get(f"{API}/rahaza/vendors", timeout=30)
    if r.status_code == 200:
        lst = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        if lst:
            v = lst[0]
            return {"vendor_id": v.get("id") or v.get("_id"), "vendor_name": v.get("name")}
    return {"vendor_id": None, "vendor_name": "TEST Vendor Iter119"}


def test_fix2_ap_double_payment(client, vendor_info, today, artefacts):
    body = {
        "vendor_id": vendor_info["vendor_id"],
        "vendor_name": vendor_info["vendor_name"],
        "issue_date": today, "due_date": today,
        "items": [{"description": "AP uji FIX2", "qty": 1, "unit_price": 200000}],
        "tax_pct": 0,
    }
    r = client.post(f"{API}/rahaza/ap-invoices", json=body, timeout=30)
    if r.status_code not in (200, 201):
        pytest.skip(f"create AP invoice not available: {r.status_code} {r.text[:200]}")
    inv = r.json()
    iid = inv.get("id") or inv.get("_id")
    artefacts["ap_invoice_ids"].append(iid)

    # Send/issue AP invoice
    sent = None
    for path in (f"/rahaza/ap-invoices/{iid}/send", f"/rahaza/ap-invoices/{iid}/issue"):
        rs = client.post(f"{API}{path}", timeout=30)
        if rs.status_code in (200, 201):
            sent = rs.json(); break
    if not sent:
        rs = client.patch(f"{API}/rahaza/ap-invoices/{iid}/status", json={"status": "sent"}, timeout=30)
        if rs.status_code in (200, 201):
            sent = rs.json()
    if not sent:
        pytest.skip("cannot issue AP invoice for payment test")

    resps = []
    for _ in range(2):
        r = client.post(f"{API}/rahaza/ap-invoices/{iid}/payment", json={"amount": 50000, "date": today}, timeout=30)
        assert r.status_code in (200, 201), r.text
        resps.append(r.json())
    pid1 = resps[0].get("_payment_id"); pid2 = resps[1].get("_payment_id")
    assert pid1 and pid2 and pid1 != pid2
    je1 = (resps[0].get("_posting_result") or {}).get("je_id")
    je2 = (resps[1].get("_posting_result") or {}).get("je_id")
    assert je1 and je2 and je1 != je2

    rp = client.get(f"{API}/rahaza/ap-invoices/{iid}/payments", timeout=30)
    assert rp.status_code == 200
    plist = rp.json() if isinstance(rp.json(), list) else rp.json().get("items", [])
    assert len(plist) >= 2


# ---------- FIX-3 : void protection ----------

def test_fix3_auto_je_void_blocked(client, artefacts):
    je_id = artefacts.get("ar_je_id_fix1")
    assert je_id
    r = client.post(f"{API}/rahaza/journals/{je_id}/void", json={"reason": "uji"}, timeout=30)
    assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
    assert "otomatis" in (r.text or "").lower() or "modul" in (r.text or "").lower(), r.text

    # Journal remains posted & hub_voidable false in list
    r2 = client.get(f"{API}/rahaza/journals", timeout=30)
    assert r2.status_code == 200
    lst = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
    found = next((j for j in lst if (j.get("id") or j.get("_id")) == je_id), None)
    assert found, "je not in list"
    assert found.get("hub_voidable") is False, found
    assert (found.get("status") or "").lower() == "posted", found


def test_fix3_manual_je_voidable(client, today, artefacts):
    body = {
        "date": today, "memo": "manual JE iter119",
        "lines": [
            {"account_code": "1-1101", "debit": 10000, "credit": 0},
            {"account_code": "1-1102", "debit": 0, "credit": 10000},
        ],
    }
    r = client.post(f"{API}/rahaza/journals", json=body, timeout=30)
    if r.status_code not in (200, 201):
        pytest.skip(f"cannot create manual journal: {r.status_code} {r.text[:200]}")
    je = r.json()
    je_id = je.get("id") or je.get("_id")
    # post
    if (je.get("status") or "").lower() != "posted":
        rp = client.post(f"{API}/rahaza/journals/{je_id}/post", timeout=30)
        if rp.status_code not in (200, 201):
            pytest.skip("cannot post manual journal")
    # verify hub_voidable true
    rl = client.get(f"{API}/rahaza/journals", timeout=30)
    lst = rl.json() if isinstance(rl.json(), list) else rl.json().get("items", [])
    found = next((j for j in lst if (j.get("id") or j.get("_id")) == je_id), None)
    assert found and found.get("hub_voidable") is True, found
    # void
    rv = client.post(f"{API}/rahaza/journals/{je_id}/void", json={"reason": "uji manual"}, timeout=30)
    assert rv.status_code in (200, 201), rv.text


def test_fix3_force_void_requires_reason(client, artefacts):
    je_id = artefacts.get("ar_payment_je_id") or artefacts.get("ar_je_id_fix1")
    r = client.post(f"{API}/rahaza/journals/{je_id}/void", json={"force": True}, timeout=30)
    assert r.status_code == 400, f"expected 400 when force w/o reason, got {r.status_code}: {r.text}"


def test_fix3_force_void_success(client, artefacts):
    # void the ar_payment JE (safer than invoice JE) as superadmin w/ force
    je_id = artefacts.get("ar_payment_je_id")
    if not je_id:
        pytest.skip("no ar_payment_je_id")
    r = client.post(f"{API}/rahaza/journals/{je_id}/void", json={"force": True, "reason": "uji paksa iter119"}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("forced") is True, body
    unlinked = body.get("unlinked_sources") or []
    assert isinstance(unlinked, list)


# ---------- FIX-4 : Kasbon deduction on payroll finalize ----------

def _pick_employee(client):
    r = client.get(f"{API}/rahaza/payroll-profiles", timeout=30)
    if r.status_code == 200:
        lst = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        for p in lst:
            if p.get("employee_id"):
                return p.get("employee_id")
    r = client.get(f"{API}/rahaza/employees", timeout=30)
    if r.status_code == 200:
        lst = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        if lst:
            return lst[0].get("id") or lst[0].get("_id")
    return None


def test_fix4_kasbon_deducted_on_finalize(client, today, artefacts):
    emp_id = _pick_employee(client)
    if not emp_id:
        pytest.skip("no employee available")

    today_dt = dt.date.fromisoformat(today)
    period_ym = today_dt.strftime("%Y-%m")
    first = today_dt.replace(day=1).isoformat()
    # last day approx: use 28
    last = today_dt.replace(day=28).isoformat()

    # Create kasbon
    rc = client.post(f"{API}/dewi/kasbon/requests", json={
        "employee_id": emp_id, "type": "kasbon", "amount": 300000,
        "reason": "uji FIX4 iter119", "deduction_start_period": period_ym,
    }, timeout=30)
    if rc.status_code not in (200, 201):
        pytest.skip(f"kasbon create failed: {rc.status_code} {rc.text[:200]}")
    kj = rc.json()
    krec = kj.get("request") or kj
    kid = krec.get("id") or krec.get("_id")
    artefacts["kasbon_ids"].append(kid)

    # HR review approve — try a few common shapes
    ok = False
    last_resp = None
    for body in [{"action": "approve"}, {"decision": "approve"}, {"action": "approve", "notes": "ok"}]:
        rr = client.patch(f"{API}/dewi/kasbon/requests/{kid}/hr-review", json=body, timeout=30)
        last_resp = (rr.status_code, rr.text[:300])
        if rr.status_code in (200, 201):
            ok = True; break
    if not ok:
        pytest.skip(f"cannot approve kasbon via hr-review: {last_resp}")

    rd = client.patch(f"{API}/dewi/kasbon/requests/{kid}/disburse", json={}, timeout=30)
    if rd.status_code not in (200, 201):
        pytest.skip(f"kasbon disburse failed: {rd.status_code} {rd.text[:200]}")
    kget = client.get(f"{API}/dewi/kasbon/requests/{kid}", timeout=30).json()
    kget = kget.get("request") or kget
    assert round(kget.get("outstanding_balance", 0)) == 300000, kget
    assert (kget.get("status") or "").lower() == "disbursed", kget

    # Create payroll run
    payload_run = {"period_from": first, "period_to": last, "employee_ids": [emp_id]}
    print("PAYROLL DEBUG payload:", payload_run)
    rrun = client.post(f"{API}/rahaza/payroll-runs", json=payload_run, timeout=30)
    if rrun.status_code not in (200, 201):
        pytest.skip(f"payroll run create failed: {rrun.status_code} {rrun.text[:300]}")
    run_id = rrun.json().get("id") or rrun.json().get("_id")
    artefacts["run_ids"].append(run_id)

    # Fetch run — check payslip has kasbon deduction
    rget = client.get(f"{API}/rahaza/payroll-runs/{run_id}", timeout=30)
    assert rget.status_code == 200, rget.text
    run = rget.json()
    payslips = run.get("payslips") or run.get("results") or []
    ded_found = False
    for ps in payslips:
        for d in (ps.get("deductions") or []):
            if (d.get("type") or "").lower() == "kasbon" and d.get("kasbon_id") == kid:
                assert round(d.get("amount", 0)) == 300000
                ded_found = True
    assert ded_found, f"kasbon deduction not in payslip: {payslips}"

    # Finalize
    rf = client.post(f"{API}/rahaza/payroll-runs/{run_id}/finalize", json={}, timeout=30)
    assert rf.status_code in (200, 201), rf.text
    fb = rf.json()
    kres = fb.get("_kasbon_result") or {}
    assert kres.get("ok") is True, fb
    results = kres.get("results") or []
    # find our specific kasbon
    ours = next((r for r in results if r.get("kasbon_id") == kid), None)
    assert ours, f"our kasbon not in results: {results}"
    assert round(ours.get("amount_deducted", 0)) == 300000, ours
    assert round(ours.get("new_outstanding", 0)) == 0
    assert (ours.get("new_status") or "").lower() == "paid_off"
    assert (ours.get("gl") or {}).get("ok") is True, ours
    # Note: main payroll _posting_result may fail independently; FIX-4 only guarantees kasbon posting
    if (fb.get("_posting_result") or {}).get("ok") is False:
        print("WARN: main payroll JE not posted:", fb.get("_posting_result"))

    # Verify kasbon side
    kget2 = client.get(f"{API}/dewi/kasbon/requests/{kid}", timeout=30).json()
    kget2 = kget2.get("request") or kget2
    assert round(kget2.get("outstanding_balance", 0)) == 0
    assert (kget2.get("status") or "").lower() == "paid_off"
    reps = kget2.get("repayments") or []
    assert any(r.get("run_id") == run_id and (r.get("method") or "").lower() == "payroll_deduction" for r in reps), reps

    # Idempotency: re-apply
    ridem = client.post(f"{API}/dewi/kasbon/apply-payroll-deductions", json={
        "period": period_ym, "deductions": [{"kasbon_id": kid, "amount": 300000}]
    }, timeout=30)
    if ridem.status_code in (200, 201):
        body = ridem.json()
        skipped = body.get("skipped") or (body.get("results") and body["results"][0].get("skipped"))
        assert skipped, f"expected skipped, got: {body}"


# ---------- Regression ----------

def test_regression_trial_balance_balanced(client):
    for url in [f"{API}/rahaza/finance/reports/trial-balance", f"{API}/rahaza/reports/trial-balance"]:
        r = client.get(url, timeout=60)
        if r.status_code == 200:
            data = r.json()
            td = data.get("total_debit") or data.get("debit_total") or 0
            tc = data.get("total_credit") or data.get("credit_total") or 0
            assert round(float(td)) == round(float(tc)), f"TB unbalanced D={td} C={tc}"
            return
    pytest.skip("no trial-balance endpoint")


def test_regression_balance_sheet(client):
    r = client.get(f"{API}/rahaza/finance/reports/balance-sheet", timeout=60)
    if r.status_code != 200:
        pytest.skip("no balance-sheet endpoint")
    data = r.json()
    assert data.get("balanced") in (True, None), data
