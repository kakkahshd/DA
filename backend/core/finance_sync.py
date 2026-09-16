"""core.finance_sync — SATU mesin sinkron master keuangan ↔ bagan akun (idempoten, aman diulang).

Dijalankan saat start server dan lewat POST /api/rahaza/finance/sync-masters. Menjaga:
1. Tiap akun kas/bank/dompet di CoA punya SATU rekening di Kas & Bank (kode rekening = kode akun) → tidak ada duplikat GL.
2. Auto Akun: vendor CMT menunjuk SSOT `vendor_partners` dgn induk 2-1110 (Hutang Vendor CMT); klien maklon → 1-1305.
3. Profil posting `cmt_ap_invoice.credit_ap` = 2-1110.
4. Backfill sub-ledger untuk semua entitas yang belum punya (vendor CMT, supplier, pelanggan, toko, klien maklon, rekening).
5. Toko online: akun pendapatan per toko (4-11xx) + sub-ledger piutang 1-1303-<toko> + baris Peta Akun Channel (kunci = kode toko);
   akun pendapatan toko lama tanpa toko & tanpa jurnal dinonaktifkan.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

CMT_AP_PARENT = "2-1110"
MAKLON_AR_PARENT = "1-1305"
CHANNEL_AR_PARENT = "1-1303"
REVENUE_GROUP = {"shopee": "4-1110", "tiktok": "4-1120", "tokopedia": "4-1130"}
NAME_ALIASES = {"ghs": "grosirhijabsragen"}


def _now():
    return datetime.now(timezone.utc)


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(shopee|tiktok|tokopedia|penjualan|toko)\b", " ", s)
    s = " ".join(s.split())
    return NAME_ALIASES.get(s, s)


async def _sync_cash_accounts(db, report: dict):
    from core.fin_statements import cash_account_codes
    codes = await cash_account_codes(db)
    linked = {r["gl_account_code"] async for r in db.rahaza_cash_accounts.find({"gl_account_code": {"$ne": None}}, {"gl_account_code": 1})}
    created = []
    async for acc in db.rahaza_coa_accounts.find({"code": {"$in": sorted(codes)}, "active": True, "is_group": False}, {"_id": 0}):
        if acc["code"] in linked:
            continue
        is_cash = acc["code"].startswith("1-11")
        name = acc["name"]
        bank_name = "" if is_cash else (name.split("–")[0].split("-")[0].strip() if name.lower().startswith("bank") else name.split("–")[0].strip())
        if await db.rahaza_cash_accounts.find_one({"code": acc["code"]}):
            await db.rahaza_cash_accounts.update_one({"code": acc["code"]}, {"$set": {"gl_account_code": acc["code"], "updated_at": _now()}})
        else:
            await db.rahaza_cash_accounts.insert_one({
                "id": str(uuid.uuid4()), "code": acc["code"], "name": name, "type": "cash" if is_cash else "bank",
                "bank_name": bank_name, "account_number": "", "opening_balance": 0.0, "notes": "dibuat otomatis dari Bagan Akun",
                "gl_account_code": acc["code"], "active": True, "created_at": _now(), "updated_at": _now(), "created_from": "coa_sync"})
        created.append(acc["code"])
    report["cash_accounts_created"] = created


async def _sync_auto_settings(db, report: dict):
    from routes.coa_auto import DEFAULT_ENTITY_TYPES, get_auto_settings
    settings = await get_auto_settings(db)
    et = settings.get("entity_types") or {}
    changed = {}
    cv = et.get("cmt_vendor") or {}
    if cv.get("collection") != "vendor_partners" or cv.get("parent_code") == "2-1100":
        et["cmt_vendor"] = {**DEFAULT_ENTITY_TYPES["cmt_vendor"], "enabled": cv.get("enabled", True)}
        changed["cmt_vendor"] = et["cmt_vendor"]["parent_code"]
    if "maklon_client" not in et:
        et["maklon_client"] = dict(DEFAULT_ENTITY_TYPES["maklon_client"])
        changed["maklon_client"] = MAKLON_AR_PARENT
    if changed:
        await db.rahaza_coa_auto_settings.update_one({"id": "default"}, {"$set": {"entity_types": et, "updated_at": _now()}})
    report["auto_settings_changed"] = changed
    prof = await db.rahaza_posting_profiles.find_one({"event_type": "cmt_ap_invoice"}, {"_id": 0, "mapping": 1})
    if prof and (prof.get("mapping") or {}).get("credit_ap") != CMT_AP_PARENT:
        await db.rahaza_posting_profiles.update_one({"event_type": "cmt_ap_invoice"}, {"$set": {"mapping.credit_ap": CMT_AP_PARENT, "updated_at": _now()}})
        report["posting_profile_fixed"] = {"cmt_ap_invoice.credit_ap": CMT_AP_PARENT}


async def _backfill_subledgers(db, report: dict, user):
    from routes.coa_auto import ensure_subledger_for_entity, get_auto_settings
    settings = await get_auto_settings(db)
    done = {}
    for etype, cfg in (settings.get("entity_types") or {}).items():
        if not cfg.get("enabled") or not cfg.get("collection"):
            continue
        tf = cfg.get("target_field") or "gl_account_code"
        n = 0
        async for ent in db[cfg["collection"]].find({"$or": [{tf: None}, {tf: {"$exists": False}}, {tf: ""}], "active": {"$ne": False}}, {"_id": 0}):
            if cfg["collection"] == "marketing_platform_accounts":
                ent = {**ent, "code": ent.get("account_code") or ent.get("code"), "name": ent.get("account_name") or ent.get("name")}
            res = await ensure_subledger_for_entity(db, etype, ent, user)
            if res.get("ok"):
                n += 1
        done[etype] = n
    report["subledgers_created"] = done


async def _next_code(db, group: str) -> str:
    codes = [a["code"] async for a in db.rahaza_coa_accounts.find({"code": {"$regex": f"^{group[:5]}\\d$"}}, {"code": 1})]
    nums = [int(c[-1]) for c in codes if c[-1].isdigit()]
    nxt = max(nums + [0]) + 1
    if nxt > 9:
        raise ValueError(f"kelompok {group} penuh")
    return f"{group[:5]}{nxt}"


async def _sync_stores(db, report: dict):
    stores = await db.marketing_platform_accounts.find({"active": {"$ne": False}}, {"_id": 0}).to_list(500)
    rev_accounts = {a["code"]: a async for a in db.rahaza_coa_accounts.find({"code": {"$regex": "^4-11[123]\\d$"}, "is_group": False}, {"_id": 0})}
    used, created, mapped = set(), [], []
    for s in stores:
        platform = (s.get("platform") or "").lower()
        group = REVENUE_GROUP.get(platform)
        if not group:
            continue
        code = s.get("coa_revenue_code")
        if not code or code not in rev_accounts:
            key = _norm(s.get("account_name"))
            match = next((c for c, a in rev_accounts.items() if c.startswith(group[:5]) and _norm(a["name"]) == key and c not in used), None)
            if not match:
                match = await _next_code(db, group)
                doc = {"id": str(uuid.uuid4()), "code": match, "name": f"Penjualan – {s.get('account_name')}", "type": "REVENUE", "parent_code": group,
                       "is_group": False, "normal_balance": "CREDIT", "flags": {"store_account_code": s.get("account_code")}, "cash_flow_group": "OPR",
                       "active": True, "created_at": _now(), "updated_at": _now(), "created_by": "system", "created_by_name": "finance_sync"}
                await db.rahaza_coa_accounts.insert_one(doc)
                rev_accounts[match] = doc
                created.append(match)
            else:
                await db.rahaza_coa_accounts.update_one({"code": match}, {"$set": {"active": True, "flags.store_account_code": s.get("account_code")}})
            code = match
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_revenue_code": code, "updated_at": _now()}})
        used.add(code)
        ar = (await db.marketing_platform_accounts.find_one({"id": s["id"]}, {"_id": 0, "ar_account_code": 1}) or {}).get("ar_account_code") or CHANNEL_AR_PARENT
        await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_receivable_code": ar}})
        # Rekening pencairan default (1-1201) supaya penarikan saldo bisa dijurnal; owner boleh mengganti di Kelola Akun.
        if not (s.get("coa_cash_code") or "").strip() and await db.rahaza_coa_accounts.find_one({"code": "1-1201", "active": True}, {"_id": 0}):
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_cash_code": "1-1201", "coa_cash_source": "default"}})
        ck = s.get("account_code")
        existing = await db.rahaza_channel_gl_mapping.find_one({"channel_key": ck}, {"_id": 0})
        if existing:
            await db.rahaza_channel_gl_mapping.update_one({"channel_key": ck}, {"$set": {"debit_ar": ar, "credit_revenue": code, "active": True, "updated_at": _now()}})
        else:
            await db.rahaza_channel_gl_mapping.insert_one({"id": str(uuid.uuid4()), "channel_key": ck, "channel_label": s.get("account_name"), "platform": platform,
                                                           "debit_ar": ar, "credit_revenue": code, "active": True, "created_at": _now(), "updated_at": _now()})
        mapped.append((ck, code, ar))
    deactivated = []
    for c, a in rev_accounts.items():
        if c in used or not a.get("active", True) or c[-1] == "0" or "lain" in a["name"].lower():
            continue  # sub-total/header, "Lain-lain" (penampung) tetap hidup
        if await db.rahaza_journal_lines.count_documents({"account_code": c}) or await db.marketing_platform_accounts.count_documents({"coa_revenue_code": c}):
            continue
        await db.rahaza_coa_accounts.update_one({"code": c}, {"$set": {"active": False, "updated_at": _now(), "deactivated_reason": "toko tidak ada di master (finance_sync)"}})
        deactivated.append(c)
    stale = await db.rahaza_channel_gl_mapping.update_many({"channel_key": {"$nin": [s.get("account_code") for s in stores]}, "active": True},
                                                            {"$set": {"active": False, "updated_at": _now()}})
    report["stores"] = {"mapped": mapped, "revenue_created": created, "revenue_deactivated": deactivated, "channel_map_deactivated": stale.modified_count}


async def _sync_revenue_flags(db, report: dict) -> None:
    """Akun penjualan per toko 4-11xx: flags is_sales/channel hilang saat migrasi 4-digit
    → validator Kelola Akun menolak akun pendapatan toko. Pulihkan dari namanya (idempoten)."""
    n = 0
    async for a in db.rahaza_coa_accounts.find(
            {"type": "REVENUE", "code": {"$regex": r"^4-11\d\d$"}, "is_group": {"$ne": True}},
            {"_id": 0, "code": 1, "name": 1, "flags": 1}):
        flags = a.get("flags") or {}
        nm = (a.get("name") or "").lower()
        ch = next((c for c in ("shopee", "tiktok", "tokopedia", "lazada") if c in nm), None)
        upd = {}
        if not flags.get("is_sales"):
            upd["flags.is_sales"] = True
        if ch and flags.get("channel") != ch:
            upd["flags.channel"] = ch
        if upd:
            await db.rahaza_coa_accounts.update_one({"code": a["code"]}, {"$set": upd})
            n += 1
    report["revenue_flags_fixed"] = n


async def sync_finance_masters(db, user: dict | None = None) -> dict:
    report: dict = {}
    await _sync_auto_settings(db, report)
    await _sync_revenue_flags(db, report)
    await _sync_cash_accounts(db, report)
    await _backfill_subledgers(db, report, user)
    await _sync_stores(db, report)
    return report
