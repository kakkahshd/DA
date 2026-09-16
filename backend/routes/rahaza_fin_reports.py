"""
PT Rahaza — Phase F1 Finance Reports
Currently: Trial Balance (per account, per period range).
(F2: P&L, Balance Sheet, Journal List; F3: Cash Flow)
"""
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc
from datetime import date
from typing import Optional
import io

from core.fin_statements import (
    compute_trial_balance, compute_worksheet, compute_profit_loss_monthly, compute_balance_sheet_monthly,
    compute_cash_flow_by_account, xlsx_profit_loss_monthly, xlsx_balance_sheet_monthly, xlsx_worksheet, xlsx_cash_flow,
)

router = APIRouter(prefix="/api/rahaza/finance/reports", tags=["rahaza-fin-reports"])


@router.get("/trial-balance")
async def trial_balance(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    as_of: Optional[str] = Query(None),
    show_zero: bool = False,
):
    """Aggregate posted journal lines per account within date range.
    Shows: account_code, account_name, type, total_debit, total_credit, net (debit - credit).
    Opening balance: sum of all lines BEFORE from_date (if provided), then add period movement.
    `as_of` = alias `to` (konsisten dgn neraca).
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = as_of or today
    return await compute_trial_balance(db, from_date, to_date, show_zero)


@router.get("/worksheet")
async def worksheet(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    show_zero: bool = False,
):
    """Neraca lajur: saldo awal · mutasi · saldo akhir · kolom Laba Rugi · kolom Neraca + baris laba bersih penyeimbang."""
    await require_auth(request)
    return await compute_worksheet(get_db(), from_date, to_date or date.today().isoformat(), show_zero)


@router.get("/profit-loss-monthly")
async def profit_loss_monthly(request: Request, year: int = Query(..., ge=2000, le=2100)):
    """Laba rugi 12 kolom bulan (Jan–Des) + total + akumulasi, ala sheet Laba-12."""
    await require_auth(request)
    return await compute_profit_loss_monthly(get_db(), year)


@router.get("/balance-sheet-monthly")
async def balance_sheet_monthly(request: Request, year: int = Query(..., ge=2000, le=2100)):
    """Neraca per akhir tiap bulan (12 kolom), ala sheet Neraca-12."""
    await require_auth(request)
    return await compute_balance_sheet_monthly(get_db(), year)


@router.get("/export-xlsx")
async def export_xlsx(
    request: Request,
    report: str = Query(..., pattern="^(profit-loss-monthly|balance-sheet-monthly|worksheet|cash-flow)$"),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    show_zero: bool = False,
):
    """Ekspor Excel memakai perhitungan yang SAMA dengan layar (core.fin_statements)."""
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if report in ("profit-loss-monthly", "balance-sheet-monthly"):
        y = year or int(today[:4])
        if report == "profit-loss-monthly":
            data, fname = xlsx_profit_loss_monthly(await compute_profit_loss_monthly(db, y)), f"laba-rugi-12-bulan-{y}.xlsx"
        else:
            data, fname = xlsx_balance_sheet_monthly(await compute_balance_sheet_monthly(db, y)), f"neraca-12-bulan-{y}.xlsx"
    elif report == "worksheet":
        to_ = to_date or today
        data, fname = xlsx_worksheet(await compute_worksheet(db, from_date, to_, show_zero)), f"neraca-lajur-{from_date or 'awal'}-{to_}.xlsx"
    else:
        to_ = to_date or today
        from_ = from_date or f"{today[:4]}-01-01"
        data, fname = xlsx_cash_flow(await _cash_flow_data(db, from_, to_)), f"arus-kas-{from_}-{to_}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/general-ledger")
async def general_ledger(
    request: Request,
    account_code: str = Query(...),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Return all lines for a specific account within a date range, with running balance."""
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = today
    acc = await db.rahaza_coa_accounts.find_one({"code": account_code}, {"_id": 0})
    if not acc:
        raise HTTPException(404, f"Akun '{account_code}' tidak ditemukan.")

    # opening balance
    opening_net = 0.0
    if from_date:
        pipe_op = [
            {"$match": {"account_code": account_code, "date": {"$lt": from_date}}},
            {"$group": {"_id": None, "debit": {"$sum": "$debit"}, "credit": {"$sum": "$credit"}}},
        ]
        async for r in db.rahaza_journal_lines.aggregate(pipe_op):
            opening_net = (r.get("debit", 0) or 0) - (r.get("credit", 0) or 0)

    q = {"account_code": account_code}
    if from_date and to_date:
        q["date"] = {"$gte": from_date, "$lte": to_date}
    elif to_date:
        q["date"] = {"$lte": to_date}

    rows_raw = await db.rahaza_journal_lines.find(q, {"_id": 0}).sort([("date", 1), ("created_at", 1)]).to_list(100000)

    running = opening_net
    lines = []
    for r in rows_raw:
        running = running + (r.get("debit", 0) or 0) - (r.get("credit", 0) or 0)
        # Convert running to display debit or credit based on normal balance
        if acc["normal_balance"] == "DEBIT":
            balance = running
        else:
            balance = -running
        lines.append({
            "date": r["date"],
            "je_number": r.get("je_number"),
            "description": r.get("description") or "",
            "source": r.get("source_module"),
            "debit": r.get("debit", 0),
            "credit": r.get("credit", 0),
            "balance": round(balance, 2),
        })
    end_balance = lines[-1]["balance"] if lines else (opening_net if acc["normal_balance"] == "DEBIT" else -opening_net)
    return {
        "account": {"code": acc["code"], "name": acc["name"], "type": acc["type"], "normal_balance": acc["normal_balance"]},
        "meta": {"from": from_date, "to": to_date},
        "opening_balance": round((opening_net if acc["normal_balance"] == "DEBIT" else -opening_net), 2),
        "lines": lines,
        "end_balance": round(end_balance, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: PROFIT & LOSS / INCOME STATEMENT
# ═══════════════════════════════════════════════════════════════════════════
_BS_KNOWN = {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "COGS", "EXPENSE", "OTHER_INCOME", "OTHER_EXPENSE"}
_BS_LEGACY = {"CURRENT_ASSET": "ASSET", "FIXED_ASSET": "ASSET", "OTHER": "OTHER_INCOME",
              "INCOME": "REVENUE", "CURRENT_LIABILITY": "LIABILITY"}


def _bs_type(acc: dict) -> str:
    """Tipe laporan yang dikenal; tipe legacy/tak dikenal dipetakan (fallback prefix kode)."""
    t = (acc.get("type") or "").upper()
    if t in _BS_KNOWN:
        return t
    if t in _BS_LEGACY:
        return _BS_LEGACY[t]
    return {"1": "ASSET", "2": "LIABILITY", "3": "EQUITY", "4": "REVENUE", "5": "COGS"}.get(
        (acc.get("code") or "")[:1], "EXPENSE")


async def _aggregate_by_account(db, match: dict):
    """Return dict {account_code: {debit, credit}} from posted journal lines."""
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$account_code",
            "debit": {"$sum": "$debit"},
            "credit": {"$sum": "$credit"},
        }},
    ]
    rows = {r["_id"]: r async for r in db.rahaza_journal_lines.aggregate(pipeline)}
    return rows


@router.get("/profit-loss")
async def profit_loss(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """F2: Income Statement / Profit & Loss.
    Grouping: REVENUE, OTHER_INCOME (credit − debit = income positive)
              COGS, EXPENSE, OTHER_EXPENSE (debit − credit = expense positive)
    Net Income = (Revenue + Other Income) − (COGS + Expense + Other Expense)
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = today
    if not from_date:
        from_date = f"{today[:4]}-01-01"

    match = {"date": {"$gte": from_date, "$lte": to_date}, "source_module": {"$ne": "year_end_close"}}  # M-09: jurnal penutup bukan L/R
    per_acc = await _aggregate_by_account(db, match)

    # Get all leaf accounts for types of interest
    type_groups = {
        "REVENUE": {"label": "Pendapatan", "accounts": []},
        "OTHER_INCOME": {"label": "Pendapatan Lain-lain", "accounts": []},
        "COGS": {"label": "Harga Pokok Penjualan (HPP)", "accounts": []},
        "EXPENSE": {"label": "Beban Operasional", "accounts": []},
        "OTHER_EXPENSE": {"label": "Beban Lain-lain", "accounts": []},
    }
    accounts = await db.rahaza_coa_accounts.find(
        {"type": {"$in": list(type_groups.keys())}, "is_group": False},
        {"_id": 0},
    ).sort("code", 1).to_list(5000)  # B-13: akun nonaktif bersaldo tetap ikut (sama dgn neraca)

    total_revenue = 0.0
    total_other_income = 0.0
    total_cogs = 0.0
    total_expense = 0.0
    total_other_expense = 0.0

    for acc in accounts:
        code = acc["code"]
        agg = per_acc.get(code, {"debit": 0, "credit": 0})
        d = float(agg.get("debit") or 0)
        c = float(agg.get("credit") or 0)
        if acc["type"] in ("REVENUE", "OTHER_INCOME"):
            # income = credit - debit (revenue normal balance = credit)
            amount = round(c - d, 2)
            row = {
                "code": code, "name": acc["name"], "type": acc["type"],
                "amount": amount, "debit": round(d, 2), "credit": round(c, 2),
            }
            type_groups[acc["type"]]["accounts"].append(row)
            if acc["type"] == "REVENUE":
                total_revenue += amount
            else:
                total_other_income += amount
        else:
            # expense/cogs = debit - credit (normal balance = debit)
            amount = round(d - c, 2)
            row = {
                "code": code, "name": acc["name"], "type": acc["type"],
                "amount": amount, "debit": round(d, 2), "credit": round(c, 2),
            }
            type_groups[acc["type"]]["accounts"].append(row)
            if acc["type"] == "COGS":
                total_cogs += amount
            elif acc["type"] == "EXPENSE":
                total_expense += amount
            else:
                total_other_expense += amount

    gross_profit = round(total_revenue - total_cogs, 2)
    operating_income = round(gross_profit - total_expense, 2)
    net_income = round(operating_income + total_other_income - total_other_expense, 2)

    return {
        "meta": {"from": from_date, "to": to_date},
        "groups": {
            "revenue": {"label": type_groups["REVENUE"]["label"], "accounts": type_groups["REVENUE"]["accounts"], "total": round(total_revenue, 2)},
            "cogs": {"label": type_groups["COGS"]["label"], "accounts": type_groups["COGS"]["accounts"], "total": round(total_cogs, 2)},
            "expense": {"label": type_groups["EXPENSE"]["label"], "accounts": type_groups["EXPENSE"]["accounts"], "total": round(total_expense, 2)},
            "other_income": {"label": type_groups["OTHER_INCOME"]["label"], "accounts": type_groups["OTHER_INCOME"]["accounts"], "total": round(total_other_income, 2)},
            "other_expense": {"label": type_groups["OTHER_EXPENSE"]["label"], "accounts": type_groups["OTHER_EXPENSE"]["accounts"], "total": round(total_other_expense, 2)},
        },
        "totals": {
            "revenue": round(total_revenue, 2),
            "cogs": round(total_cogs, 2),
            "gross_profit": gross_profit,
            "expense": round(total_expense, 2),
            "operating_income": operating_income,
            "other_income": round(total_other_income, 2),
            "other_expense": round(total_other_expense, 2),
            "net_income": net_income,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: BALANCE SHEET
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/balance-sheet")
async def balance_sheet(
    request: Request,
    as_of: Optional[str] = Query(None),
):
    """F2: Balance Sheet (as of date).
    Assets = Liabilities + Equity.
    Current year earnings derived from P&L net income (YTD up to as_of).
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not as_of:
        as_of = today

    # aggregate all posted lines up to as_of
    match = {"date": {"$lte": as_of}}
    per_acc = await _aggregate_by_account(db, match)

    # get leaf accounts for Balance Sheet types + revenue/expense for net income calc
    # C-04: akun NONAKTIF yang punya saldo tetap ikut (kalau tidak, neraca tak seimbang);
    # tipe legacy (CURRENT_ASSET/OTHER/...) dinormalisasi lewat _bs_type().
    accounts = await db.rahaza_coa_accounts.find(
        {"is_group": False},
        {"_id": 0},
    ).sort("code", 1).to_list(5000)

    assets = []
    liabilities = []
    equity = []
    total_assets = 0.0
    total_liabilities = 0.0
    total_equity = 0.0
    # compute net income (same as P&L within YTD)
    total_rev = 0.0
    total_cogs = 0.0
    total_exp = 0.0
    total_oi = 0.0
    total_oe = 0.0
    unknown_types = []

    for acc in accounts:
        code = acc["code"]
        agg = per_acc.get(code, {"debit": 0, "credit": 0})
        d = float(agg.get("debit") or 0)
        c = float(agg.get("credit") or 0)
        if not acc.get("active", True) and d == 0 and c == 0:
            continue
        acc_type = _bs_type(acc)
        if acc_type != (acc.get("type") or "").upper():
            unknown_types.append({"code": code, "type": acc.get("type"), "treated_as": acc_type})

        if acc_type == "ASSET":
            bal = round(d - c, 2)
            if bal != 0:
                assets.append({"code": code, "name": acc["name"], "amount": bal})
            total_assets += bal
        elif acc_type == "LIABILITY":
            bal = round(c - d, 2)
            if bal != 0:
                liabilities.append({"code": code, "name": acc["name"], "amount": bal})
            total_liabilities += bal
        elif acc_type == "EQUITY":
            bal = round(c - d, 2)
            if bal != 0:
                equity.append({"code": code, "name": acc["name"], "amount": bal})
            total_equity += bal
        elif acc_type == "REVENUE":
            total_rev += round(c - d, 2)
        elif acc_type == "COGS":
            total_cogs += round(d - c, 2)
        elif acc_type == "EXPENSE":
            total_exp += round(d - c, 2)
        elif acc_type == "OTHER_INCOME":
            total_oi += round(c - d, 2)
        elif acc_type == "OTHER_EXPENSE":
            total_oe += round(d - c, 2)

    current_earnings = round(total_rev - total_cogs - total_exp + total_oi - total_oe, 2)
    # add "Laba/Rugi Tahun Berjalan" as computed equity line (virtual, from P&L)
    if current_earnings != 0:
        equity.append({
            "code": "LABA_BERJALAN",
            "name": "Laba/Rugi Tahun Berjalan (Komputasi)",
            "amount": current_earnings,
            "computed": True,
        })
        total_equity += current_earnings

    total_liab_equity = round(total_liabilities + total_equity, 2)
    balanced = round(total_assets, 2) == total_liab_equity
    # Baris jurnal pada akun yang TIDAK ADA di COA (mis. sub-akun dihapus) → neraca diam-diam tak seimbang.
    known = {a["code"] for a in accounts}
    orphan_accounts = [{"code": code, "debit": round(float(v.get("debit") or 0), 2), "credit": round(float(v.get("credit") or 0), 2)}
                       for code, v in per_acc.items() if code not in known]

    return {
        "meta": {"as_of": as_of},
        "assets": {"accounts": assets, "total": round(total_assets, 2)},
        "liabilities": {"accounts": liabilities, "total": round(total_liabilities, 2)},
        "equity": {"accounts": equity, "total": round(total_equity, 2)},
        "totals": {
            "assets": round(total_assets, 2),
            "liabilities": round(total_liabilities, 2),
            "equity": round(total_equity, 2),
            "liab_plus_equity": total_liab_equity,
            "current_earnings": current_earnings,
            "diff": round(round(total_assets, 2) - total_liab_equity, 2),
        },
        "balanced": balanced,
        "type_warnings": unknown_types,
        "orphan_account_lines": orphan_accounts,
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: JOURNAL LIST (audit trail with filter)
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/journal-list")
async def journal_list(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    source: Optional[str] = None,
    status: Optional[str] = None,
    account_code: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
):
    """F2: filtered journal list (audit trail).
    Optionally filter by account_code: returns only JEs whose lines touch that account.
    """
    await require_auth(request)
    db = get_db()
    q = {}
    if from_date and to_date:
        q["date"] = {"$gte": from_date, "$lte": to_date}
    elif from_date:
        q["date"] = {"$gte": from_date}
    elif to_date:
        q["date"] = {"$lte": to_date}
    if source:
        q["source_module"] = source
    if status:
        q["status"] = status

    if account_code:
        # find JE ids that have line with account_code
        line_rows = await db.rahaza_journal_lines.find(
            {"account_code": account_code, **({"date": q["date"]} if "date" in q else {})},
            {"_id": 0, "je_id": 1},
        ).to_list(100000)
        je_ids = list({r["je_id"] for r in line_rows})
        if not je_ids:
            return {"meta": {"from": from_date, "to": to_date, "source": source, "status": status, "account_code": account_code}, "rows": [], "total_debit": 0, "total_credit": 0}
        q["id"] = {"$in": je_ids}

    rows = await db.rahaza_journal_entries.find(q, {"_id": 0}).sort([("date", -1), ("je_number", -1)]).limit(limit).to_list(limit)
    # summarize totals (only posted)
    total_debit = sum(float(r.get("total_debit") or 0) for r in rows if r.get("status") == "posted")
    total_credit = sum(float(r.get("total_credit") or 0) for r in rows if r.get("status") == "posted")

    return {
        "meta": {"from": from_date, "to": to_date, "source": source, "status": status, "account_code": account_code},
        "rows": serialize_doc(rows),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "count": len(rows),
    }


# ═══════════════════════════════════════════════════════════════════════════
# F3: CASH FLOW STATEMENT (direct method via cash_movements ledger)
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/cash-flow")
async def cash_flow(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """F3: Cash Flow Statement (metode direct).
    Sumber utama: rahaza_cash_movements (category-based grouping ke Operating/Investing/Financing) —
    agregasi di Mongo (tanpa batas 500 baris). Ditambah `by_account`: arus kas dari akun lawan jurnal
    yang menyentuh akun kas/bank, dikelompokkan lewat tag OPR/INV/PND akun (ala sheet Arus-K).
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    return await _cash_flow_data(db, from_date or f"{today[:4]}-01-01", to_date or today)


INVESTING_CATS = {"asset_purchase", "asset_sale", "investment"}
FINANCING_CATS = {"loan_proceeds", "loan_repayment", "owner_investment", "owner_withdrawal", "dividend"}


def _bucket(cat: str) -> str:
    c = (cat or "").lower()
    if c in INVESTING_CATS:
        return "investing"
    if c in FINANCING_CATS:
        return "financing"
    return "operating"  # default: ar_payment, ap_payment, expense, payroll, …


async def _cash_flow_data(db, from_date: str, to_date: str) -> dict:
    # 1) Agregasi kategori × arah langsung di Mongo — dulu to_list(500) memotong data pada volume nyata
    pipe = [{"$match": {"date": {"$gte": from_date, "$lte": to_date}}},
            {"$group": {"_id": {"cat": {"$ifNull": ["$category", "other_operating"]}, "dir": "$direction"},
                        "amount": {"$sum": {"$ifNull": ["$amount", 0]}}, "count": {"$sum": 1}}}]
    activities = {"operating": {}, "investing": {}, "financing": {}}
    async for r in db.rahaza_cash_movements.aggregate(pipe):
        cat = r["_id"]["cat"] or "other_operating"
        slot = activities[_bucket(cat)].setdefault(cat, {"inflow": 0.0, "outflow": 0.0, "net": 0.0, "count": 0})
        amt = float(r.get("amount") or 0)
        if r["_id"]["dir"] == "out":
            slot["outflow"] += amt
            slot["net"] -= amt
        else:
            slot["inflow"] += amt
            slot["net"] += amt
        slot["count"] += int(r.get("count") or 0)

    def _format_bucket(b):
        rows = [{"category": cat, "label": cat.replace("_", " ").title(), "inflow": round(s["inflow"], 2),
                 "outflow": round(s["outflow"], 2), "net": round(s["net"], 2), "count": s["count"]} for cat, s in b.items()]
        rows.sort(key=lambda r: r["category"])
        return {"items": rows, "total": round(sum(r["net"] for r in rows), 2)}

    operating, investing, financing = (_format_bucket(activities[k]) for k in ("operating", "investing", "financing"))
    net_change = round(operating["total"] + investing["total"] + financing["total"], 2)

    # 2) Kas awal & akhir — saldo dari Buku Besar (Iter 122); opening = saldo kini − Σ mutasi sejak from_date
    from routes.rahaza_posting import cash_accounts_with_gl
    cash_accs = await cash_accounts_with_gl(db, {})
    closing_cash_now = sum(float(a.get("balance") or 0) for a in cash_accs)
    delta_since_from = 0.0
    async for r in db.rahaza_cash_movements.aggregate([
        {"$match": {"date": {"$gte": from_date}}},
        {"$group": {"_id": "$direction", "amount": {"$sum": {"$ifNull": ["$amount", 0]}}}}]):
        delta_since_from += -float(r["amount"] or 0) if r["_id"] == "out" else float(r["amount"] or 0)
    opening_cash = closing_cash_now - delta_since_from
    closing_cash = round(opening_cash + net_change, 2)

    by_account = await compute_cash_flow_by_account(db, from_date, to_date)

    return {
        "meta": {"from": from_date, "to": to_date, "method": "direct"},
        "activities": {
            "operating": {"label": "Aktivitas Operasi", **operating},
            "investing": {"label": "Aktivitas Investasi", **investing},
            "financing": {"label": "Aktivitas Pendanaan", **financing},
        },
        "totals": {
            "operating": operating["total"],
            "investing": investing["total"],
            "financing": financing["total"],
            "net_change_in_cash": net_change,
            "opening_cash": round(opening_cash, 2),
            "closing_cash": closing_cash,
        },
        "cash_accounts": [
            {"id": a.get("id"), "code": a.get("code"), "name": a.get("name"), "type": a.get("type"), "balance": round(float(a.get("balance") or 0), 2)}
            for a in cash_accs
        ],
        "by_account": by_account,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# M-01 (Iter 116) — Nilai Persediaan Barang Jadi dari lapisan FIFO vs saldo GL 1-1404
# ═══════════════════════════════════════════════════════════════════════════════
FG_INVENTORY_ACCOUNT = "1-1404"


@router.get("/fg-inventory-valuation")
async def fg_inventory_valuation(request: Request, as_of: Optional[str] = Query(None)):
    """Kartu stok FG (fg_cost_layers qty_remaining × unit_cost) per SKU, dibandingkan
    dengan saldo GL 1-1404 sampai `as_of` (default hari ini). Lapisan = posisi SAAT INI;
    GL = per tanggal. Selisih dijelaskan: lapisan belum berjurnal (WIP→FG belum diposting),
    lapisan tanpa biaya, dan stok fisik tanpa lapisan."""
    await require_auth(request)
    db = get_db()
    return await compute_fg_valuation(db, as_of or date.today().isoformat())


async def compute_fg_valuation(db, as_of_date: str) -> dict:
    """Inti laporan M-01 — dipakai endpoint di atas DAN cron `fg-valuation-check`."""
    layers = await db.fg_cost_layers.find({}, {"_id": 0}).to_list(20000)
    per_mat: dict = {}
    unposted_value, unposted_layers, uncosted_qty = 0.0, 0, 0
    for ly in layers:
        mid = ly.get("material_id") or ""
        rem = float(ly.get("qty_remaining") or 0)
        uc = float(ly.get("unit_cost") or 0)
        m = per_mat.setdefault(mid, {"material_id": mid, "sku": ly.get("sku") or "", "layer_qty": 0.0, "layer_value": 0.0,
                                     "layers_open": 0, "uncosted_qty": 0.0, "unposted_value": 0.0, "stock_qty": 0.0})
        if rem > 0:
            m["layer_qty"] += rem
            m["layer_value"] += rem * uc
            m["layers_open"] += 1
            if uc <= 0:
                m["uncosted_qty"] += rem
                uncosted_qty += rem
        if not ly.get("gl_je_id") and float(ly.get("total_cost") or 0) > 0:
            # belum ada JE WIP→FG utk lapisan ini → GL 1-1404 belum memuat nilainya
            unposted_layers += 1
            unposted_value += float(ly.get("total_cost") or 0)
            m["unposted_value"] += float(ly.get("total_cost") or 0)

    stock_rows = await db.rahaza_material_stock.aggregate([
        {"$match": {"inventory_category": "fg_internal"}},
        {"$group": {"_id": "$material_id", "qty": {"$sum": {"$ifNull": ["$qty", 0]}}}},
    ]).to_list(20000)
    for s in stock_rows:
        mid = s["_id"] or ""
        m = per_mat.setdefault(mid, {"material_id": mid, "sku": "", "layer_qty": 0.0, "layer_value": 0.0,
                                     "layers_open": 0, "uncosted_qty": 0.0, "unposted_value": 0.0, "stock_qty": 0.0})
        m["stock_qty"] = float(s.get("qty") or 0)

    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": [k for k in per_mat if k]}},
                                                              {"_id": 0, "id": 1, "code": 1, "name": 1})}
    rows = []
    for mid, m in per_mat.items():
        info = mats.get(mid) or {}
        m["code"] = info.get("code") or m["sku"] or mid[:8]
        m["name"] = info.get("name") or ""
        m["avg_unit_cost"] = round(m["layer_value"] / m["layer_qty"], 2) if m["layer_qty"] > 0 else 0.0
        m["qty_diff"] = round(m["stock_qty"] - m["layer_qty"], 2)
        for k in ("layer_qty", "layer_value", "uncosted_qty", "unposted_value", "stock_qty"):
            m[k] = round(m[k], 2)
        if m["layer_qty"] or m["stock_qty"] or m["unposted_value"]:
            rows.append(m)
    rows.sort(key=lambda r: -r["layer_value"])

    agg = await _aggregate_by_account(db, {"date": {"$lte": as_of_date}, "account_code": FG_INVENTORY_ACCOUNT})
    a = agg.get(FG_INVENTORY_ACCOUNT) or {}
    gl_balance = round(float(a.get("debit") or 0) - float(a.get("credit") or 0), 2)
    layer_value = round(sum(r["layer_value"] for r in rows), 2)
    difference = round(layer_value - gl_balance, 2)
    explained = round(difference - unposted_value, 2)
    return {
        "as_of": as_of_date, "gl_account": FG_INVENTORY_ACCOUNT,
        "rows": rows,
        "totals": {"stock_qty": round(sum(r["stock_qty"] for r in rows), 2), "layer_qty": round(sum(r["layer_qty"] for r in rows), 2),
                   "layer_value": layer_value, "gl_balance": gl_balance, "difference": difference,
                   "unposted_layers": unposted_layers, "unposted_value": round(unposted_value, 2),
                   "uncosted_qty": round(uncosted_qty, 2), "unexplained_difference": explained},
        "reconciled": abs(difference) < 1,
        "explained": abs(explained) < 1,
        "notes": [
            "Nilai lapisan = Σ qty_remaining × unit_cost (FIFO, posisi saat ini).",
            "Saldo GL = Dr − Cr akun 1-1404 sampai tanggal as_of.",
            "unposted_value = lapisan bernilai yang belum punya JE WIP→FG (jalankan Backfill WIP→FG).",
            "uncosted_qty = stok berlapisan tetapi unit_cost 0 (harga bahan/upah PO belum terisi).",
        ],
    }
