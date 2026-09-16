"""
M-09 — Tutup Tahun (Iter 114).
Jurnal penutup 31 Des: semua akun L/R (REVENUE/COGS/EXPENSE/OTHER_*) di-nol-kan, selisih → Laba Ditahan (3-2000).
Syarat: 12 periode tahun itu closed/locked. Idempoten per tahun (source_ref yearend:{year}); bisa dibalik (void).
Laporan L/R mengecualikan source_module 'year_end_close'; neraca MEMAKAI-nya (laba tahun lalu pindah ke Laba Ditahan).
"""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from auth import log_activity, require_auth, serialize_doc
from database import get_db
from routes.rahaza_fin_reports import _aggregate_by_account, _bs_type
from routes.rahaza_periods import _require_fin_mgr
from routes.rahaza_posting import _create_posted_je, _find_existing_je, _get_account

router = APIRouter(prefix="/api/rahaza/year-end", tags=["rahaza-year-end"])
SOURCE_MODULE = "year_end_close"
RETAINED_EARNINGS = "3-2000"
PL_TYPES = {"REVENUE", "COGS", "EXPENSE", "OTHER_INCOME", "OTHER_EXPENSE"}


def _now():
    return datetime.now(timezone.utc)


async def _preview(db, year: int) -> dict:
    periods = await db.rahaza_periods.find({"year": year}, {"_id": 0, "period_code": 1, "status": 1}).to_list(12)
    by_code = {p["period_code"]: p["status"] for p in periods}
    open_periods = [f"{year}-{m:02d}" for m in range(1, 13) if by_code.get(f"{year}-{m:02d}") not in ("closed", "locked")]
    match = {"date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"}, "source_module": {"$ne": SOURCE_MODULE}}
    per_acc = await _aggregate_by_account(db, match)
    accounts = await db.rahaza_coa_accounts.find({"is_group": False}, {"_id": 0, "code": 1, "name": 1, "type": 1}).to_list(5000)
    lines, net = [], 0.0
    for acc in accounts:
        t = _bs_type(acc)
        if t not in PL_TYPES:
            continue
        agg = per_acc.get(acc["code"])
        if not agg:
            continue
        bal = round(float(agg.get("credit") or 0) - float(agg.get("debit") or 0), 2)  # + = kredit (pendapatan)
        if bal == 0:
            continue
        net += bal
        lines.append({"account_code": acc["code"], "account_name": acc["name"], "type": t,
                      "debit": max(0, bal), "credit": -bal if bal < 0 else 0})
    existing = await _find_existing_je(db, SOURCE_MODULE, f"yearend:{year}")
    re_acc = await _get_account(db, RETAINED_EARNINGS)
    return {"year": year, "open_periods": open_periods, "net_income": round(net, 2), "lines": lines,
            "retained_earnings_account": RETAINED_EARNINGS, "retained_earnings_ok": bool(re_acc),
            "already_closed": bool(existing),
            "existing_je": {"id": existing["id"], "je_number": existing.get("je_number")} if existing else None,
            "can_close": not open_periods and not existing and bool(re_acc) and bool(lines)}


@router.get("")
async def list_closings(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_year_end_closings.find({}, {"_id": 0}).sort("year", -1).to_list(50)
    return {"closings": serialize_doc(rows)}


@router.get("/preview")
async def preview_year_end(request: Request, year: int):
    await require_auth(request)
    return await _preview(get_db(), year)


@router.post("/close")
async def close_year(request: Request):
    user = await _require_fin_mgr(request)
    db = get_db()
    body = await request.json()
    year = int((body or {}).get("year") or 0)
    if year < 2000 or year >= date.today().year + 1:
        raise HTTPException(400, "Tahun tidak valid.")
    pv = await _preview(db, year)
    if pv["already_closed"]:
        raise HTTPException(400, f"Tahun {year} sudah ditutup (JE {pv['existing_je']['je_number']}).")
    if pv["open_periods"]:
        raise HTTPException(400, f"Periode belum closed: {', '.join(pv['open_periods'])}. Tutup semua periode dulu.")
    if not pv["retained_earnings_ok"]:
        raise HTTPException(400, f"Akun Laba Ditahan {RETAINED_EARNINGS} tidak ditemukan/aktif.")
    if not pv["lines"]:
        raise HTTPException(400, f"Tidak ada saldo L/R tahun {year} untuk ditutup.")
    net = pv["net_income"]
    lines = [{"account_code": ln["account_code"], "debit": ln["debit"], "credit": ln["credit"],
              "description": f"Penutupan {ln['account_name']} {year}"} for ln in pv["lines"]]
    lines.append({"account_code": RETAINED_EARNINGS, "debit": -net if net < 0 else 0, "credit": max(0, net),
                  "description": f"Laba (rugi) bersih {year} → Laba Ditahan"})
    res = await _create_posted_je(db, date(year, 12, 31), f"Jurnal Penutup Tahun {year} — laba bersih {net:,.0f} ke Laba Ditahan",
                                  SOURCE_MODULE, f"yearend:{year}", lines, user, allow_closed_period=True)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "Gagal membuat jurnal penutup.")
    doc = {"id": str(uuid.uuid4()), "year": year, "je_id": res["je_id"], "je_number": res["je_number"], "net_income": net,
           "lines_count": len(pv["lines"]), "closed_at": _now(), "closed_by": user.get("name", ""), "status": "closed"}
    await db.rahaza_year_end_closings.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "year_end_close", "periods", f"year={year} je={res['je_number']} net={net}")
    return serialize_doc(doc)


@router.post("/{year}/reverse")
async def reverse_year_end(year: int, request: Request):
    user = await _require_fin_mgr(request)
    db = get_db()
    je = await _find_existing_je(db, SOURCE_MODULE, f"yearend:{year}")
    if not je:
        raise HTTPException(404, f"Tahun {year} belum ditutup.")
    await db.rahaza_journal_entries.update_one({"id": je["id"]}, {"$set": {
        "status": "voided", "voided_at": _now(), "voided_by": user.get("id"), "void_reason": "Pembatalan tutup tahun", "updated_at": _now()}})
    await db.rahaza_journal_lines.delete_many({"je_id": je["id"]})
    await db.rahaza_year_end_closings.update_one({"year": year, "status": "closed"}, {"$set": {
        "status": "reversed", "reversed_at": _now(), "reversed_by": user.get("name", "")}})
    await log_activity(user["id"], user.get("name", ""), "year_end_reverse", "periods", f"year={year} je={je.get('je_number')}")
    return {"ok": True, "year": year, "voided_je": je.get("je_number")}
