"""Iter113 QA — H-08 period guard + H-02 payroll components via API + regressions."""
import os, sys, requests, datetime as dt
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')
BASE = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
MONGO = os.environ['MONGO_URL']; DB = os.environ['DB_NAME']
db = MongoClient(MONGO)[DB]

def log(ok, msg):
    print(('PASS' if ok else 'FAIL') + ' - ' + msg)
    if not ok: FAIL.append(msg)

FAIL = []

# baseline
je_before = db.rahaza_journal_entries.count_documents({})
jl_before = db.rahaza_journal_lines.count_documents({})
print(f"BASELINE: JE={je_before} JL={jl_before}")

# --- Login ---
r = requests.post(f"{BASE}/api/auth/login", json={"email":"admin@garment.com","password":"Admin@123"})
assert r.status_code==200, r.text
tok = r.json()['token']
H = {"Authorization": f"Bearer {tok}"}

# --- H-08: policy endpoint ---
r = requests.get(f"{BASE}/api/rahaza/periods/policy", headers=H)
log(r.status_code==200, f"GET /periods/policy -> {r.status_code}")
if r.status_code==200:
    d = r.json()
    log(d.get('future_days_max')==31, f"policy.future_days_max=31 ({d.get('future_days_max')})")
    log(2026 in d.get('auto_years',[]), f"policy.auto_years contains 2026: {d.get('auto_years')}")

# --- H-08: manual journal, future >31d ---
future = (dt.date.today() + dt.timedelta(days=60)).isoformat()
payload_future = {"date": future, "memo":"QA future","lines":[
    {"account_code":"1-1201","debit":1000,"credit":0},
    {"account_code":"6-2900","debit":0,"credit":1000}
], "post": True}
r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, json=payload_future)
log(r.status_code==400 and 'masa depan' in r.text.lower(), f"future date post -> {r.status_code} {r.text[:150]}")

# 2019 date
payload_2019 = dict(payload_future); payload_2019['date']='2019-01-15'; payload_2019['memo']='QA 2019'
r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, json=payload_2019)
log(r.status_code==400 and ('belum dibuka' in r.text.lower() or 'belum' in r.text.lower()), f"2019 date post -> {r.status_code} {r.text[:150]}")
log(db.rahaza_periods.count_documents({'year':2019})==0, "no 2019 periods auto-created")

# close/reopen current month
today = dt.date.today()
month_str = today.strftime('%Y-%m')
period_date = today.replace(day=15).isoformat()
r_close = requests.post(f"{BASE}/api/rahaza/periods/{month_str}/close", headers=H)
log(r_close.status_code==200, f"close {month_str} -> {r_close.status_code} {r_close.text[:120]}")

payload_now = {"date": period_date, "memo":"QA now closed","lines":[
    {"account_code":"1-1201","debit":1000,"credit":0},
    {"account_code":"6-2900","debit":0,"credit":1000}
], "post": True}
r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, json=payload_now)
log(r.status_code==423 and 'closed' in r.text.lower(), f"post to closed period -> {r.status_code} {r.text[:150]}")

r_reopen = requests.post(f"{BASE}/api/rahaza/periods/{month_str}/reopen", headers=H)
log(r_reopen.status_code==200, f"reopen {month_str} -> {r_reopen.status_code}")

payload_now['memo']='QA now reopened'
r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, json=payload_now)
log(r.status_code==200 and r.json().get('status')=='posted', f"post after reopen -> {r.status_code} status={r.json().get('status') if r.status_code==200 else None}")
qa_je_id = r.json().get('id') if r.status_code==200 else None

# Draft with future date
payload_draft = dict(payload_future); payload_draft['post']=False; payload_draft['memo']='QA draft future'
r = requests.post(f"{BASE}/api/rahaza/journals", headers=H, json=payload_draft)
print(f"NOTE draft-future-post -> {r.status_code} (either 200 or 400 is acceptable)")
qa_draft_id = None
if r.status_code==200:
    qa_draft_id = r.json().get('id')

# ==================== H-02 PAYROLL ====================
# Setup synthetic data
db.rahaza_payroll_runs.delete_many({'id': {'$in':['run-qa-agent','run-qa-agent-bad']}})
db.rahaza_payslips.delete_many({'run_id': {'$in':['run-qa-agent','run-qa-agent-bad']}})

db.rahaza_payroll_runs.insert_one({
    'id':'run-qa-agent','run_number':'PR-QA-AGENT',
    'period_from':'2026-08-01','period_to':'2026-08-31',
    'status':'finalized','total_gross':8000000,'total_deductions':410000,'total_net':7590000
})
db.rahaza_payslips.insert_many([
    {'id':'ps-qa-1','run_id':'run-qa-agent','employee_id':'e1','gross':5000000,'total_deductions':350000,'net':4650000,
     'deductions':[
        {'type':'pph21','amount':100000},
        {'type':'bpjs_kesehatan','amount':50000},
        {'type':'bpjs_jht','amount':100000},
        {'type':'kasbon','amount':75000},
        {'type':'late','amount':25000},
     ]},
    {'id':'ps-qa-2','run_id':'run-qa-agent','employee_id':'e2','gross':3000000,'total_deductions':60000,'net':2940000,
     'deductions':[
        {'type':'bpjs_jp','amount':30000},
        {'type':'lwop','amount':30000},
     ]},
])

# post-je
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent/post-to-gl", headers=H)
print(f"post-je -> {r.status_code} {r.text[:400]}")
log(r.status_code==200, "payroll post-je 200")
je_id_run = None
if r.status_code==200:
    resp = r.json()
    je_id_run = resp.get('je_id') or resp.get('journal_entry_id')
    # find JE by source_ref
    je_doc = db.rahaza_journal_entries.find_one({'source_ref':'payroll:run-qa-agent'})
    log(je_doc is not None, f"JE source_ref payroll:run-qa-agent exists")
    if je_doc:
        je_id_run = je_doc['id']
        lines = list(db.rahaza_journal_lines.find({'je_id':je_id_run}))
        by_acc = {}
        for l in lines:
            by_acc.setdefault(l['account_code'], {'dr':0,'cr':0})
            by_acc[l['account_code']]['dr'] += l.get('debit',0)
            by_acc[l['account_code']]['cr'] += l.get('credit',0)
        print(f"JE lines by acct: {by_acc}")
        log(by_acc.get('6-2100',{}).get('dr')==7945000, f"6-2100 Dr=7945000 (got {by_acc.get('6-2100',{}).get('dr')})")
        log(by_acc.get('2-1200',{}).get('cr')==7590000+75000, f"2-1200 Cr=7665000 (got {by_acc.get('2-1200',{}).get('cr')})")
        log(by_acc.get('2-1301',{}).get('cr')==100000, f"2-1301 Cr=100000 (got {by_acc.get('2-1301',{}).get('cr')})")
        log(by_acc.get('2-1500',{}).get('cr')==180000, f"2-1500 Cr=180000 (got {by_acc.get('2-1500',{}).get('cr')})")
        total_dr = sum(v['dr'] for v in by_acc.values())
        total_cr = sum(v['cr'] for v in by_acc.values())
        log(abs(total_dr-total_cr)<0.01, f"JE balanced dr={total_dr} cr={total_cr}")

# idempotent
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent/post-to-gl", headers=H)
print(f"post-je (2nd) -> {r.status_code} {r.text[:200]}")
log(r.status_code==200 and (r.json().get('already_posted') is True or 'already' in r.text.lower()), "post-je idempotent already_posted")
je_count_after_repost = db.rahaza_journal_entries.count_documents({'source_ref':'payroll:run-qa-agent'})
log(je_count_after_repost==1, f"only 1 JE for payroll:run-qa-agent (got {je_count_after_repost})")

# pay-bpjs
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent/pay-bpjs", headers=H, json={"payment_date":"2026-09-05"})
print(f"pay-bpjs -> {r.status_code} {r.text[:300]}")
log(r.status_code==200, "pay-bpjs 200")
if r.status_code==200:
    run = db.rahaza_payroll_runs.find_one({'id':'run-qa-agent'})
    log(run.get('bpjs_payment_amount')==180000, f"bpjs_payment_amount=180000 (got {run.get('bpjs_payment_amount')})")
    je_bpjs = db.rahaza_journal_entries.find_one({'source_ref':'payroll:run-qa-agent:bpjs'}) or \
              db.rahaza_journal_entries.find_one({'source_ref': {'$regex':'run-qa-agent.*bpjs'}})
    log(je_bpjs is not None, f"JE bpjs found: {je_bpjs.get('id') if je_bpjs else None}")

# pay-pph21
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent/pay-pph21", headers=H, json={"payment_date":"2026-09-05"})
print(f"pay-pph21 -> {r.status_code} {r.text[:300]}")
log(r.status_code==200, "pay-pph21 200")
if r.status_code==200:
    run = db.rahaza_payroll_runs.find_one({'id':'run-qa-agent'})
    log(run.get('pph21_payment_amount')==100000, f"pph21_payment_amount=100000 (got {run.get('pph21_payment_amount')})")

# pay-bpjs again -> 400
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent/pay-bpjs", headers=H, json={"payment_date":"2026-09-05"})
log(r.status_code==400, f"pay-bpjs 2nd -> {r.status_code} (expect 400)")

# --- Bad run: inconsistent totals ---
db.rahaza_payroll_runs.insert_one({
    'id':'run-qa-agent-bad','run_number':'PR-QA-AGENT-BAD',
    'period_from':'2026-08-01','period_to':'2026-08-31',
    'status':'finalized','total_gross':8000000,'total_deductions':999999,'total_net':7590000
})
db.rahaza_payslips.insert_many([
    {'id':'ps-qa-bad-1','run_id':'run-qa-agent-bad','employee_id':'e1','gross':5000000,'total_deductions':350000,'net':4650000,
     'deductions':[{'type':'pph21','amount':100000},{'type':'bpjs_kesehatan','amount':50000},
                   {'type':'bpjs_jht','amount':100000},{'type':'kasbon','amount':75000},{'type':'late','amount':25000}]},
    {'id':'ps-qa-bad-2','run_id':'run-qa-agent-bad','employee_id':'e2','gross':3000000,'total_deductions':60000,'net':2940000,
     'deductions':[{'type':'bpjs_jp','amount':30000},{'type':'lwop','amount':30000}]},
])
r = requests.post(f"{BASE}/api/rahaza/payroll-runs/run-qa-agent-bad/post-to-gl", headers=H)
print(f"post-je (bad) -> {r.status_code} {r.text[:300]}")
# expect ok False or 400
body = {}
try: body = r.json()
except Exception: pass
inconsistent = ('tidak konsisten' in r.text.lower()) or (body.get('ok') is False) or r.status_code>=400
log(inconsistent, f"bad run flagged inconsistent (status={r.status_code})")
bad_je = db.rahaza_journal_entries.count_documents({'source_ref':'payroll:run-qa-agent-bad'})
log(bad_je==0, f"no JE for bad run (got {bad_je})")
bad_run = db.rahaza_payroll_runs.find_one({'id':'run-qa-agent-bad'})
log(bool(bad_run.get('post_error')), f"post_error saved: {bad_run.get('post_error')}")

# --- Regression ---
r = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H)
log(r.status_code==200, f"balance-sheet -> {r.status_code}")
if r.status_code==200:
    bs = r.json()
    log(bs.get('balanced') is True, f"balance-sheet balanced=true (got {bs.get('balanced')})")
    log(len(bs.get('orphan_account_lines',[]))==0, f"orphan_account_lines empty (got {bs.get('orphan_account_lines')})")

r = requests.get(f"{BASE}/api/finance/bank-recon/summary", headers=H)
log(r.status_code==200, f"finance/bank-recon/summary -> {r.status_code}")
r = requests.get(f"{BASE}/api/rahaza/ar-aging", headers=H)
log(r.status_code==200, f"rahaza/ar-aging -> {r.status_code}")

# ==================== CLEANUP ====================
print("\n--- CLEANUP ---")
# delete QA payroll JEs and lines
for src in ['payroll:run-qa-agent','payroll:run-qa-agent-bad','bpjspay:run-qa-agent','pph21pay:run-qa-agent']:
    for je in list(db.rahaza_journal_entries.find({'source_ref': {'$regex': f'^{src}'}})):
        db.rahaza_journal_lines.delete_many({'je_id':je['id']})
    db.rahaza_journal_entries.delete_many({'source_ref': {'$regex': f'^{src}'}})
# QA manual JEs
for jid in [qa_je_id, qa_draft_id]:
    if jid:
        db.rahaza_journal_lines.delete_many({'je_id':jid})
        db.rahaza_journal_entries.delete_one({'id':jid})
# runs and payslips
db.rahaza_payroll_runs.delete_many({'id': {'$in':['run-qa-agent','run-qa-agent-bad']}})
db.rahaza_payslips.delete_many({'run_id': {'$in':['run-qa-agent','run-qa-agent-bad']}})

je_after = db.rahaza_journal_entries.count_documents({})
jl_after = db.rahaza_journal_lines.count_documents({})
print(f"AFTER: JE={je_after} JL={jl_after}")
log(je_after==je_before, f"JE count restored ({je_before} -> {je_after})")
log(jl_after==jl_before, f"JL count restored ({jl_before} -> {jl_after})")
log(db.rahaza_periods.count_documents({'year':2019})==0, "no 2019 periods left")
log(db.rahaza_payroll_runs.count_documents({'id': {'$regex':'^run-qa-'}})==0, "no run-qa-* left")

# orphan lines check
je_ids = set(x['id'] for x in db.rahaza_journal_entries.find({}, {'id':1}))
orphan = sum(1 for l in db.rahaza_journal_lines.find({}, {'je_id':1}) if l.get('je_id') not in je_ids)
log(orphan==0, f"no orphan JL (got {orphan})")

print(f"\n=== SUMMARY: {'ALL PASS' if not FAIL else f'{len(FAIL)} FAIL'} ===")
for f in FAIL: print('  FAIL:', f)
sys.exit(0 if not FAIL else 1)
