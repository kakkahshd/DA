"""platform_balance — saldo toko di marketplace = piutang toko ke platform.

Dua tahap yang menjadi satu-satunya pintu Marketing → Finance (keputusan pemilik):
  1. `marketing_settlements`            — dana DILEPAS platform ke saldo toko
                                          (Dr Piutang Toko / Dr potongan / Cr Pendapatan)
  2. `marketing_platform_withdrawals`   — saldo DITARIK ke rekening bank
                                          (Dr Bank / Cr Piutang Toko)
Saldo yang bisa dicairkan = Σ dana dilepas − Σ penarikan. Omzet input Marketing
(sales harian / impor pesanan) TIDAK ikut ke sini — hanya laporan.
"""
from __future__ import annotations

from typing import Iterable, Optional

SETTLEMENTS = "marketing_settlements"
WITHDRAWALS = "marketing_platform_withdrawals"


def receivable_code(account: dict) -> str:
    return ((account.get("ar_account_code") or account.get("coa_receivable_code") or "").strip())


async def _sum_by_account(db, coll: str, field: str, match: dict) -> dict:
    rows = await db[coll].aggregate([
        {"$match": match},
        {"$group": {"_id": "$account_id", "total": {"$sum": f"${field}"}, "count": {"$sum": 1}}},
    ]).to_list(2000)
    return {r["_id"]: r for r in rows if r.get("_id")}


async def platform_balances(db, account_ids: Optional[Iterable[str]] = None) -> list:
    aq = {} if account_ids is None else {"id": {"$in": list(account_ids)}}
    accounts = await db.marketing_platform_accounts.find(
        aq, {"_id": 0, "id": 1, "account_code": 1, "account_name": 1, "platform": 1, "status": 1,
             "ar_account_code": 1, "coa_receivable_code": 1, "coa_cash_code": 1}).to_list(2000)
    ids = [a["id"] for a in accounts]
    match = {"account_id": {"$in": ids}}
    released = await _sum_by_account(db, SETTLEMENTS, "net_payout", match)
    withdrawn = await _sum_by_account(db, WITHDRAWALS, "amount", match)

    codes = [c for c in (receivable_code(a) for a in accounts) if c]
    gl = {}
    if codes:
        for r in await db.rahaza_journal_lines.aggregate([
            {"$match": {"account_code": {"$in": codes}}},
            {"$group": {"_id": "$account_code",
                        "bal": {"$sum": {"$subtract": ["$debit", "$credit"]}}}},
        ]).to_list(2000):
            gl[r["_id"]] = round(float(r.get("bal") or 0), 2)

    out = []
    for a in accounts:
        rel = released.get(a["id"], {})
        wd = withdrawn.get(a["id"], {})
        code = receivable_code(a)
        rel_t = round(float(rel.get("total") or 0), 2)
        wd_t = round(float(wd.get("total") or 0), 2)
        out.append({
            "account_id": a["id"], "account_code": a.get("account_code"),
            "account_name": a.get("account_name"), "platform": a.get("platform"),
            "status": a.get("status"),
            "receivable_code": code or None, "cash_code": (a.get("coa_cash_code") or "").strip() or None,
            "released_total": rel_t, "released_count": int(rel.get("count") or 0),
            "withdrawn_total": wd_t, "withdrawn_count": int(wd.get("count") or 0),
            "balance": round(rel_t - wd_t, 2),
            "gl_balance": gl.get(code, 0.0) if code else None,
        })
    out.sort(key=lambda x: -x["balance"])
    return out


async def available_balance(db, account_id: str, exclude_withdrawal_id: str = "") -> float:
    rel = await _sum_by_account(db, SETTLEMENTS, "net_payout", {"account_id": account_id})
    wq: dict = {"account_id": account_id}
    if exclude_withdrawal_id:
        wq["id"] = {"$ne": exclude_withdrawal_id}
    wd = await _sum_by_account(db, WITHDRAWALS, "amount", wq)
    return round(float(rel.get(account_id, {}).get("total") or 0)
                 - float(wd.get(account_id, {}).get("total") or 0), 2)
