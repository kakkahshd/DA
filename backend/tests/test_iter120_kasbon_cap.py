"""Iter 120: potongan kasbon di payroll dibatasi sisa gaji (THP tidak negatif) + JE payroll seimbang."""
import os, sys, json, datetime
import requests

BASE = os.environ.get("API_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]
S = requests.Session()
tok = S.post(f"{BASE}/api/auth/login", json={"email": "admin@garment.com", "password": "Admin@123"}).json()["token"]
S.headers["Authorization"] = f"Bearer {tok}"

EMP_NAME = "Op. Demo Borongan"
today = datetime.date.today()
ym = today.strftime("%Y-%m")
emps = S.get(f"{BASE}/api/rahaza/employees", params={"limit": 500}).json()
emps = emps.get("items", emps) if isinstance(emps, dict) else emps
emp = next(e for e in emps if e.get("name") == EMP_NAME)
eid = emp["id"]

# saldo kasbon aktif sebelum uji
def active_kasbon():
    rows = S.get(f"{BASE}/api/dewi/kasbon/requests", params={"limit": 200}).json()
    rows = rows.get("requests", rows) if isinstance(rows, dict) else rows
    return [k for k in rows if k.get("employee_id") == eid and k.get("status") == "disbursed"]

before = sum(float(k["outstanding_balance"]) for k in active_kasbon())
r = S.post(f"{BASE}/api/dewi/kasbon/requests", json={"employee_id": eid, "type": "kasbon", "amount": 300000, "purpose": "uji iter120"})
assert r.status_code in (200, 201), r.text
kid = r.json()["request"]["id"]
assert S.patch(f"{BASE}/api/dewi/kasbon/requests/{kid}/hr-review", json={"action": "approve"}).status_code == 200
assert S.patch(f"{BASE}/api/dewi/kasbon/requests/{kid}/disburse", json={"deduction_start_period": ym}).status_code == 200

r = S.post(f"{BASE}/api/rahaza/payroll-runs", json={"period_from": f"{ym}-01", "period_to": today.isoformat(), "employee_ids": [eid]})
assert r.status_code == 200, r.text
run_id = r.json()["id"]
run = S.get(f"{BASE}/api/rahaza/payroll-runs/{run_id}").json()
slips = run.get("payslips") or run.get("items") or []
slip = next(s for s in slips if s["employee_id"] == eid)
gross = float(slip["gross_pay"]); net = float(slip["net_pay"])
kas = [d for d in slip["deductions"] if d.get("type") == "kasbon"]
print("gross", gross, "net", net, "kasbon deductions", json.dumps(kas, ensure_ascii=False))
assert net >= 0, "THP negatif"
assert sum(d["amount"] for d in kas) <= gross

fin = S.post(f"{BASE}/api/rahaza/payroll-runs/{run_id}/finalize").json()
print("posting", fin.get("_posting_result"))
print("kasbon", json.dumps(fin.get("_kasbon_result"), ensure_ascii=False)[:600])
assert (fin.get("_posting_result") or {}).get("ok"), fin.get("_posting_result")
kr = fin.get("_kasbon_result") or {}
assert kr.get("ok")
deducted = sum(x.get("amount_deducted", 0) for x in kr["results"] if not x.get("skipped"))
after = sum(float(k["outstanding_balance"]) for k in active_kasbon()) + sum(
    float(k["outstanding_balance"]) for k in [S.get(f"{BASE}/api/dewi/kasbon/requests/{kid}").json()["request"]] if k.get("status") != "disbursed")
print("saldo sebelum", before, "+300000 → sesudah", after, "dipotong", deducted)
assert abs((before + 300000 - deducted) - after) < 1, "saldo kasbon tidak konsisten"
print("PASS iter120 kasbon cap")
