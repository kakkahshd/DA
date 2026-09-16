"""Iter114 QA — H-07 revenue on dispatch, M-09 year-end close, period alerts.
Self-cleaning API+Mongo QA. Run: python3 tests/qa_iter114_api.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')

BASE = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
MONGO = MongoClient(os.environ['MONGO_URL'])
DB = MONGO[os.environ['DB_NAME']]

results = []
def rec(name, ok, info=''):
    results.append((name, ok, info))
    print(f"{'OK ' if ok else 'FAIL'} {name}  {info}")

def login(email, pwd):
    r = requests.post(f"{BASE}/api/auth/login", json={'email':email,'password':pwd}, timeout=30)
    r.raise_for_status()
    return r.json()['token']

def H(t): return {'Authorization': f'Bearer {t}', 'Content-Type':'application/json'}

# Baselines
je0 = DB.rahaza_journal_entries.count_documents({})
jl0 = DB.rahaza_journal_lines.count_documents({})
ar0 = DB.rahaza_ar_invoices.count_documents({})
print(f"baseline JE={je0} JL={jl0} AR={ar0}")

admin_t = login('admin@garment.com', 'Admin@123')
gudang_t = login('gudang@dewiaditya.id', 'Dewi@123')

# ============ (1) H-07 revenue on PO internal buyer dispatch ============
po_id = f"po-qa114-{uuid.uuid4().hex[:8]}"
sj_id = f"sj-qa114-{uuid.uuid4().hex[:8]}"
po_num = f"PO-QA-{uuid.uuid4().hex[:6].upper()}"
sj_num = f"SJ-QA-{uuid.uuid4().hex[:6].upper()}"

DB.production_pos.insert_one({
    'id': po_id, 'po_number': po_num, 'business_type':'internal',
    'customer_name':'Buyer QA', 'payment_terms_days': 14,
    'created_at': datetime.now(timezone.utc),
})
pi1, pi2 = f'pi1-{po_id}', f'pi2-{po_id}'
DB.po_items.insert_many([
    {'id':pi1,'po_id':po_id,'sku':'SKU-QA-A','product_name':'Kaos A','color':'H','size':'L','qty':40,'selling_price_snapshot':50000.0},
    {'id':pi2,'po_id':po_id,'sku':'SKU-QA-B','product_name':'Kaos B','color':'P','size':'M','qty':10,'selling_price_snapshot':0.0},
])
DB.buyer_shipments.insert_one({
    'id': sj_id, 'shipment_number': sj_num, 'po_id': po_id, 'po_number': po_num,
    'business_type':'internal','receiver_type':'buyer','customer_name':'Buyer QA',
    'last_dispatch':'2026-08-20T03:00:00+00:00',
    'created_at': datetime.now(timezone.utc),
})
DB.buyer_shipment_items.insert_many([
    {'id':f'bsi1-{sj_id}','shipment_id':sj_id,'po_id':po_id,'po_number':po_num,'po_item_id':pi1,
     'sku':'SKU-QA-A','product_name':'Kaos A','color':'H','size':'L',
     'qty_shipped':40,'dispatch_seq':1,'dispatch_date':'2026-08-20T03:00:00+00:00'},
    {'id':f'bsi2-{sj_id}','shipment_id':sj_id,'po_id':po_id,'po_number':po_num,'po_item_id':pi2,
     'sku':'SKU-QA-B','product_name':'Kaos B','color':'P','size':'M',
     'qty_shipped':10,'dispatch_seq':1,'dispatch_date':'2026-08-20T03:00:00+00:00'},
])

# maklon SJ (for 400)
sj_mak_id = f"sj-mak-qa-{uuid.uuid4().hex[:8]}"
DB.buyer_shipments.insert_one({
    'id': sj_mak_id, 'shipment_number': f"SJM-{uuid.uuid4().hex[:6]}",
    'po_id': po_id, 'business_type':'maklon','receiver_type':'buyer',
    'customer_name':'MakQA','last_dispatch':'2026-08-20T03:00:00+00:00',
    'created_at': datetime.now(timezone.utc),
})

try:
    # Admin post-revenue
    r = requests.post(f"{BASE}/api/buyer-shipments/{sj_id}/post-revenue", headers=H(admin_t), timeout=60)
    ok_hdr = r.status_code == 200
    data = r.json() if ok_hdr else {}
    rec('H07 post-revenue 200', ok_hdr, f"status={r.status_code} body={str(data)[:200]}")
    if ok_hdr:
        res0 = (data.get('results') or [{}])[0]
        ar_num = res0.get('ar_invoice_number')
        rec('H07 results[0].ok true', bool(res0.get('ok')), f"ok={res0.get('ok')}")
        rec('H07 total 2000000', res0.get('total') == 2000000, f"total={res0.get('total')}")
        up = res0.get('unpriced') or []
        rec('H07 unpriced SKU-B qty10', up == [{'sku':'SKU-QA-B','qty':10}], f"unpriced={up}")
        rec('H07 ar_invoice_number format', bool(ar_num) and ar_num.startswith('INV-PO-2026-'), f"num={ar_num}")

        inv = DB.rahaza_ar_invoices.find_one({'invoice_number': ar_num}) if ar_num else None
        rec('H07 AR invoice exists', bool(inv), f"found={bool(inv)}")
        if inv:
            rec('H07 status issued', inv.get('status')=='issued', f"status={inv.get('status')}")
            idt = str(inv.get('invoice_date',''))[:10]
            ddt = str(inv.get('due_date',''))[:10]
            rec('H07 invoice_date 2026-08-20', idt=='2026-08-20', f"idt={idt}")
            rec('H07 due_date 2026-09-03 (+14d)', ddt=='2026-09-03', f"ddt={ddt}")
            rec('H07 gl_je_id present', bool(inv.get('gl_je_id')), f"je={inv.get('gl_je_id')}")
            je = DB.rahaza_journal_entries.find_one({'id': inv.get('gl_je_id')}) if inv.get('gl_je_id') else None
            if je:
                rec('H07 JE posted 2026-08-20', je.get('status')=='posted' and str(je.get('date',''))[:10]=='2026-08-20',
                    f"st={je.get('status')} dt={str(je.get('date',''))[:10]}")
                lines = list(DB.rahaza_journal_lines.find({'je_id': je['id']}))
                dr = sum((l.get('debit') or 0) for l in lines if l.get('account_code','').startswith('1-13'))
                cr = sum((l.get('credit') or 0) for l in lines if l.get('account_code','').startswith('4-'))
                rec('H07 JE Dr 1-13xx = 2000000', dr==2000000, f"dr={dr}")
                rec('H07 JE Cr 4-xxxx = 2000000', cr==2000000, f"cr={cr}")

    # idempotent
    r2 = requests.post(f"{BASE}/api/buyer-shipments/{sj_id}/post-revenue", headers=H(admin_t), timeout=60)
    d2 = r2.json() if r2.status_code==200 else {}
    res20 = (d2.get('results') or [{}])[0]
    rec('H07 idempotent already true', res20.get('already') is True, f"already={res20.get('already')}")
    rec('H07 still 1 AR', DB.rahaza_ar_invoices.count_documents({'source_ref': {'$regex': sj_id}}) == 1 or
        DB.rahaza_ar_invoices.count_documents({'invoice_number': ar_num}) == 1, '')

    # GET revenue
    rg = requests.get(f"{BASE}/api/buyer-shipments/{sj_id}/revenue", headers=H(admin_t), timeout=30)
    gd = rg.json() if rg.status_code==200 else {}
    invs = gd.get('invoices') or gd.get('items') or []
    rec('H07 GET revenue 1 invoice', rg.status_code==200 and len(invs)>=1, f"status={rg.status_code} n={len(invs)}")

    # AR aging
    ra = requests.get(f"{BASE}/api/rahaza/ar-aging", headers=H(admin_t), timeout=30)
    rec('H07 ar-aging 200', ra.status_code==200, f"status={ra.status_code}")

    # gudang 403
    rg2 = requests.post(f"{BASE}/api/buyer-shipments/{sj_id}/post-revenue", headers=H(gudang_t), timeout=30)
    rec('H07 gudang 403', rg2.status_code==403, f"status={rg2.status_code}")

    # maklon 400
    rm = requests.post(f"{BASE}/api/buyer-shipments/{sj_mak_id}/post-revenue", headers=H(admin_t), timeout=30)
    rec('H07 maklon 400', rm.status_code==400, f"status={rm.status_code} body={rm.text[:150]}")
finally:
    # cleanup H07
    if 'ar_num' in dir():
        pass
    # gather je_ids from ar invoices then delete
    je_ids = [x['gl_je_id'] for x in DB.rahaza_ar_invoices.find({'source_ref': {'$regex': sj_id}}, {'gl_je_id':1}) if x.get('gl_je_id')]
    # fallback: find AR by shipment
    for x in DB.rahaza_ar_invoices.find({'invoice_number': {'$regex':'^INV-PO-2026-'}}):
        if x.get('gl_je_id'): je_ids.append(x['gl_je_id'])
    DB.rahaza_journal_lines.delete_many({'je_id': {'$in': je_ids}})
    DB.rahaza_journal_entries.delete_many({'id': {'$in': je_ids}})
    DB.rahaza_ar_invoices.delete_many({'gl_je_id': {'$in': je_ids}})
    DB.buyer_shipment_items.delete_many({'shipment_id': {'$in':[sj_id, sj_mak_id]}})
    DB.buyer_shipments.delete_many({'id': {'$in':[sj_id, sj_mak_id]}})
    DB.po_items.delete_many({'po_id': po_id})
    DB.production_pos.delete_many({'id': po_id})

# ============ (2) M-09 Year-end close 2024 ============
try:
    r = requests.post(f"{BASE}/api/rahaza/periods/ensure-year", headers=H(admin_t), json={'year':2024}, timeout=30)
    ej = r.json() if r.status_code==200 else {}
    rec('M09 ensure-year 2024 created 12', r.status_code==200 and (ej.get('created')==12 or DB.rahaza_periods.count_documents({'period_code':{'$regex':'^2024-'}})==12),
        f"status={r.status_code} body={str(ej)[:150]}")

    # Post 2 manual journals
    j1 = {'date':'2024-06-15','description':'QA114 rev','lines':[
        {'account_code':'1-1301','debit':1000000,'credit':0},
        {'account_code':'4-1100','debit':0,'credit':1000000}], 'post': True}
    r1 = requests.post(f"{BASE}/api/rahaza/journals", headers=H(admin_t), json=j1, timeout=30)
    rec('M09 journal 2024-06-15 post 200', r1.status_code==200, f"status={r1.status_code} body={r1.text[:150]}")
    je_j1 = (r1.json() or {}).get('id') if r1.status_code==200 else None

    j2 = {'date':'2024-07-15','description':'QA114 exp','lines':[
        {'account_code':'6-2900','debit':400000,'credit':0},
        {'account_code':'1-1201','debit':0,'credit':400000}], 'post': True}
    r2 = requests.post(f"{BASE}/api/rahaza/journals", headers=H(admin_t), json=j2, timeout=30)
    rec('M09 journal 2024-07-15 post 200', r2.status_code==200, f"status={r2.status_code}")
    je_j2 = (r2.json() or {}).get('id') if r2.status_code==200 else None

    # Preview
    rp = requests.get(f"{BASE}/api/rahaza/year-end/preview?year=2024", headers=H(admin_t), timeout=30)
    pv = rp.json() if rp.status_code==200 else {}
    rec('M09 preview net_income 600000', pv.get('net_income')==600000, f"ni={pv.get('net_income')}")
    rec('M09 preview open_periods 12', len(pv.get('open_periods') or [])==12, f"n={len(pv.get('open_periods') or [])}")
    rec('M09 preview can_close false', pv.get('can_close') is False, f"cc={pv.get('can_close')}")

    # Close should 400 belum
    rc = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H(admin_t), json={'year':2024}, timeout=30)
    rec('M09 close 400 belum closed', rc.status_code==400, f"status={rc.status_code} body={rc.text[:120]}")

    # Close all 12 periods
    close_ok = 0
    for m in range(1,13):
        rk = requests.post(f"{BASE}/api/rahaza/periods/2024-{m:02d}/close", headers=H(admin_t), timeout=30)
        if rk.status_code==200: close_ok += 1
    rec('M09 close 12 periods', close_ok==12, f"closed={close_ok}")

    rp2 = requests.get(f"{BASE}/api/rahaza/year-end/preview?year=2024", headers=H(admin_t), timeout=30)
    pv2 = rp2.json() if rp2.status_code==200 else {}
    rec('M09 preview can_close true', pv2.get('can_close') is True, f"cc={pv2.get('can_close')}")

    # Close year
    rcc = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H(admin_t), json={'year':2024}, timeout=30)
    ccj = rcc.json() if rcc.status_code==200 else {}
    rec('M09 close 200', rcc.status_code==200, f"status={rcc.status_code} body={str(ccj)[:200]}")
    rec('M09 close net_income 600000', ccj.get('net_income')==600000, f"ni={ccj.get('net_income')}")
    rec('M09 close status closed', ccj.get('status')=='closed', f"st={ccj.get('status')}")

    # JE 2024-12-31 lines
    yec = DB.rahaza_year_end_closings.find_one({'year':2024})
    yec_je = yec.get('je_id') if yec else None
    yec_lines = list(DB.rahaza_journal_lines.find({'je_id': yec_je})) if yec_je else []
    dr_rev = sum((l.get('debit') or 0) for l in yec_lines if l.get('account_code')=='4-1100')
    cr_exp = sum((l.get('credit') or 0) for l in yec_lines if l.get('account_code')=='6-2900')
    cr_re = sum((l.get('credit') or 0) for l in yec_lines if l.get('account_code')=='3-2000')
    rec('M09 JE 4-1100 debit 1000000', dr_rev==1000000, f"={dr_rev}")
    rec('M09 JE 6-2900 credit 400000', cr_exp==400000, f"={cr_exp}")
    rec('M09 JE 3-2000 credit 600000', cr_re==600000, f"={cr_re}")

    # Idempotent close
    rcc2 = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H(admin_t), json={'year':2024}, timeout=30)
    rec('M09 close again 400 sudah', rcc2.status_code==400, f"status={rcc2.status_code}")

    # profit-loss excludes year-end
    rpl = requests.get(f"{BASE}/api/rahaza/finance/reports/profit-loss?from=2024-01-01&to=2024-12-31", headers=H(admin_t), timeout=30)
    pl = rpl.json() if rpl.status_code==200 else {}
    ni = (pl.get('totals') or {}).get('net_income')
    rec('M09 P/L net_income 600000 (excl close)', ni==600000, f"ni={ni}")

    # balance-sheet
    rbs = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet?as_of=2024-12-31", headers=H(admin_t), timeout=30)
    bs = rbs.json() if rbs.status_code==200 else {}
    ce = (bs.get('totals') or {}).get('current_earnings')
    rec('M09 BS balanced true', bs.get('balanced') is True, f"bal={bs.get('balanced')}")
    rec('M09 BS current_earnings 0', ce==0, f"ce={ce}")
    eq_accts = ((bs.get('equity') or {}).get('accounts') or [])
    re_line = next((a for a in eq_accts if a.get('code')=='3-2000' or a.get('account_code')=='3-2000'), None)
    amt = (re_line or {}).get('amount') or (re_line or {}).get('balance')
    rec('M09 BS 3-2000 = 600000', amt==600000, f"line={re_line}")

    # history
    rh = requests.get(f"{BASE}/api/rahaza/year-end", headers=H(admin_t), timeout=30)
    hist = rh.json() if rh.status_code==200 else {}
    clist = hist.get('closings') or hist.get('items') or []
    rec('M09 history contains 2024 closed', any((c.get('year')==2024 and c.get('status')=='closed') for c in clist), f"n={len(clist)}")

    # gudang 403
    rg3 = requests.post(f"{BASE}/api/rahaza/year-end/close", headers=H(gudang_t), json={'year':2024}, timeout=30)
    rec('M09 gudang close 403', rg3.status_code==403, f"status={rg3.status_code}")

    # reverse
    rrv = requests.post(f"{BASE}/api/rahaza/year-end/2024/reverse", headers=H(admin_t), timeout=30)
    rec('M09 reverse 200', rrv.status_code==200, f"status={rrv.status_code}")
    if yec_je:
        je_after = DB.rahaza_journal_entries.find_one({'id': yec_je})
        n_lines_after = DB.rahaza_journal_lines.count_documents({'je_id': yec_je})
        rec('M09 JE voided', (je_after or {}).get('status')=='voided', f"st={(je_after or {}).get('status')}")
        rec('M09 JE lines removed', n_lines_after==0, f"n={n_lines_after}")

    rrv2 = requests.post(f"{BASE}/api/rahaza/year-end/2024/reverse", headers=H(admin_t), timeout=30)
    rec('M09 reverse again 404', rrv2.status_code==404, f"status={rrv2.status_code}")

    rp3 = requests.get(f"{BASE}/api/rahaza/year-end/preview?year=2024", headers=H(admin_t), timeout=30)
    pv3 = rp3.json() if rp3.status_code==200 else {}
    rec('M09 preview already_closed false', pv3.get('already_closed') is False, f"ac={pv3.get('already_closed')}")
finally:
    # cleanup 2024
    for je_id in [je_j1 if 'je_j1' in dir() else None, je_j2 if 'je_j2' in dir() else None]:
        if je_id:
            DB.rahaza_journal_lines.delete_many({'je_id': je_id})
            DB.rahaza_journal_entries.delete_many({'id': je_id})
    # remove year-end JE(s)
    for y in DB.rahaza_year_end_closings.find({'year':2024}):
        if y.get('je_id'):
            DB.rahaza_journal_lines.delete_many({'je_id': y['je_id']})
            DB.rahaza_journal_entries.delete_many({'id': y['je_id']})
    DB.rahaza_year_end_closings.delete_many({'year':2024})
    DB.rahaza_periods.delete_many({'period_code':{'$regex':'^2024-'}})

# ============ (3) Period alerts 2019 ============
je_alert_ids = []
try:
    DB.rahaza_periods.delete_many({'period_code':{'$regex':'^2019-'}})
    DB.rahaza_period_alerts.delete_many({'year':{'$in':[2019,2018]}})

    j19 = {'date':'2019-03-01','description':'QA114 alert','lines':[
        {'account_code':'1-1201','debit':1000,'credit':0},
        {'account_code':'6-2900','debit':0,'credit':1000}], 'post': True}
    ra1 = requests.post(f"{BASE}/api/rahaza/journals", headers=H(admin_t), json=j19, timeout=30)
    ra2 = requests.post(f"{BASE}/api/rahaza/journals", headers=H(admin_t), json=j19, timeout=30)
    rec('ALERT 2019 posting 400 x2', ra1.status_code==400 and ra2.status_code==400, f"s1={ra1.status_code} s2={ra2.status_code}")

    ral = requests.get(f"{BASE}/api/rahaza/periods/alerts", headers=H(admin_t), timeout=30)
    aldata = ral.json() if ral.status_code==200 else {}
    alerts_list = aldata.get('alerts') or aldata.get('items') or (aldata if isinstance(aldata,list) else [])
    a2019 = next((a for a in alerts_list if a.get('year')==2019), None)
    rec('ALERT list contains 2019 open', bool(a2019) and a2019.get('status')=='open', f"a={a2019}")
    rec('ALERT 2019 source_module manual_journal', (a2019 or {}).get('source_module')=='manual_journal', f"sm={(a2019 or {}).get('source_module')}")
    rec('ALERT 2019 count>=2', (a2019 or {}).get('count',0)>=2 or (a2019 or {}).get('open_count',0)>=1, f"c={(a2019 or {}).get('count')}")

    # ensure-year 2019 → auto resolve
    rey = requests.post(f"{BASE}/api/rahaza/periods/ensure-year", headers=H(admin_t), json={'year':2019}, timeout=30)
    rec('ALERT ensure-year 2019 200', rey.status_code==200, f"status={rey.status_code}")
    a2019_after = DB.rahaza_period_alerts.find_one({'year':2019})
    rec('ALERT 2019 resolved_via ensure-year',
        (a2019_after or {}).get('status')=='resolved' and (a2019_after or {}).get('resolved_via')=='ensure-year',
        f"a={a2019_after}")

    ral2 = requests.get(f"{BASE}/api/rahaza/periods/alerts", headers=H(admin_t), timeout=30)
    ad2 = ral2.json() if ral2.status_code==200 else {}
    al2 = ad2.get('alerts') or ad2.get('items') or (ad2 if isinstance(ad2,list) else [])
    rec('ALERT list no longer contains 2019 open', not any(a.get('year')==2019 and a.get('status')=='open' for a in al2), f"n={len(al2)}")

    # 2019 posting now works
    ra3 = requests.post(f"{BASE}/api/rahaza/journals", headers=H(admin_t), json=j19, timeout=30)
    rec('ALERT 2019 posting now 200', ra3.status_code==200, f"status={ra3.status_code} body={ra3.text[:120]}")
    if ra3.status_code==200:
        je_alert_ids.append((ra3.json() or {}).get('id'))

    # 2018 manual alert insert then resolve endpoint
    aid = f"al-2018-{uuid.uuid4().hex[:8]}"
    DB.rahaza_period_alerts.insert_one({'id':aid,'year':2018,'source_module':'manual_journal','count':1,
                                        'status':'open','created_at':datetime.now(timezone.utc)})
    rres = requests.post(f"{BASE}/api/rahaza/periods/alerts/{aid}/resolve", headers=H(admin_t), timeout=30)
    rec('ALERT resolve 2018 200', rres.status_code==200, f"status={rres.status_code}")
    rres2 = requests.post(f"{BASE}/api/rahaza/periods/alerts/{aid}/resolve", headers=H(admin_t), timeout=30)
    rec('ALERT resolve 2018 again 404', rres2.status_code==404, f"status={rres2.status_code}")
finally:
    for je_id in je_alert_ids:
        if je_id:
            DB.rahaza_journal_lines.delete_many({'je_id': je_id})
            DB.rahaza_journal_entries.delete_many({'id': je_id})
    DB.rahaza_periods.delete_many({'period_code':{'$regex':'^2019-'}})
    DB.rahaza_period_alerts.delete_many({'year':{'$in':[2019,2018]}})

# ============ Regression ============
rr1 = requests.get(f"{BASE}/api/finance/bank-recon/summary", headers=H(admin_t), timeout=30)
rec('REG bank-recon summary 200', rr1.status_code==200, f"status={rr1.status_code}")
rr2 = requests.get(f"{BASE}/api/rahaza/finance/reports/balance-sheet", headers=H(admin_t), timeout=30)
bs = rr2.json() if rr2.status_code==200 else {}
rec('REG balance-sheet balanced=true, orphan=[]',
    bs.get('balanced') is True and not (bs.get('orphan_account_lines') or bs.get('orphan_accounts')),
    f"bal={bs.get('balanced')} orph={bs.get('orphan_account_lines') or bs.get('orphan_accounts')}")
rr3 = requests.get(f"{BASE}/api/rahaza/periods/policy", headers=H(admin_t), timeout=30)
rec('REG periods/policy 200', rr3.status_code==200, f"status={rr3.status_code}")

# ============ Final counts ============
je1 = DB.rahaza_journal_entries.count_documents({})
jl1 = DB.rahaza_journal_lines.count_documents({})
ar1 = DB.rahaza_ar_invoices.count_documents({})
p2019 = DB.rahaza_periods.count_documents({'period_code':{'$regex':'^2019-'}})
p2024 = DB.rahaza_periods.count_documents({'period_code':{'$regex':'^2024-'}})
al = DB.rahaza_period_alerts.count_documents({'year':{'$in':[2018,2019]}})
yec = DB.rahaza_year_end_closings.count_documents({'year':2024})
print(f"\nFINAL JE={je1} (was {je0})  JL={jl1} (was {jl0})  AR={ar1} (was {ar0})")
print(f"  periods_2019={p2019}  periods_2024={p2024}  alerts_test={al}  yec2024={yec}")
rec('CLEAN JE count restored', je1==je0, f"{je1} vs {je0}")
rec('CLEAN JL count restored', jl1==jl0, f"{jl1} vs {jl0}")
rec('CLEAN AR count restored', ar1==ar0, f"{ar1} vs {ar0}")
rec('CLEAN no 2019 periods', p2019==0, '')
rec('CLEAN no 2024 periods', p2024==0, '')
rec('CLEAN no test alerts', al==0, '')
rec('CLEAN no yec2024', yec==0, '')

# Summary
n_ok = sum(1 for _,ok,_ in results if ok)
n_tot = len(results)
print(f"\n=== {n_ok}/{n_tot} PASS ===")
for name,ok,info in results:
    if not ok: print(f"  FAIL {name}  {info}")
sys.exit(0 if n_ok==n_tot else 1)
