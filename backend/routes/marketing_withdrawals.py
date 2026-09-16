"""marketing_withdrawals — TAHAP 2: **PENARIKAN SALDO PLATFORM KE BANK**.

Saldo toko di Shopee/TikTok (akun `1-1303-xxx`, diisi oleh tahap 1 di
`marketing_settlements.py`) ditarik ke rekening bank toko. Jurnal:
    Dr Rekening Pencairan (`coa_cash_code` toko)  /  Cr Piutang Toko (`ar_account_code`)
Inilah dokumen yang dicocokkan ke MUTASI BANK (rekonsiliasi) — bukan laporan dana dilepas.

Aturan: nominal penarikan tidak boleh melebihi saldo platform yang tercatat
(Σ dana dilepas − Σ penarikan lain). Kalau dilanggar, berarti ada laporan dana
dilepas yang belum dicatat — itu yang harus diisi dulu, bukan saldonya dibiarkan minus.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from auth import require_auth
from core import marketing_account_scope as _scope
from core import platform_balance as _bal
from core import withdrawal_import as _wimport
from database import get_db
from routes.marketing_settlements import _je_still_binding, _now, _require_finance, _rp, _ser

router = APIRouter(prefix="/api/marketing/withdrawals", tags=["marketing-withdrawals"])

COLL = _bal.WITHDRAWALS
SOURCE_MODULE = "platform_withdrawal"


class WithdrawalIn(BaseModel):
    account_id: str
    withdrawal_date: str                       # YYYY-MM-DD — tanggal uang masuk bank
    amount: float = Field(gt=0)
    reference: Optional[str] = ""              # nomor penarikan di platform (bila ada)
    notes: Optional[str] = ""


class ImportRow(BaseModel):
    withdrawal_date: str
    amount: float = Field(gt=0)
    reference: Optional[str] = ""


class ImportCommitIn(BaseModel):
    account_id: str
    rows: List[ImportRow]
    filename: Optional[str] = ""


async def _annotate_rows(db, account: dict, rows: list) -> list:
    """Tandai baris yang sudah tercatat & yang membuat saldo minus (kumulatif)."""
    refs = [r["reference"] for r in rows if r.get("reference")]
    existing = {d["reference"] for d in await db[COLL].find(
        {"account_id": account["id"], "reference": {"$in": refs}}, {"_id": 0, "reference": 1}).to_list(5000)} if refs else set()
    avail = await _bal.available_balance(db, account["id"])
    running = 0.0
    for r in rows:
        if r.get("reference") and r["reference"] in existing:
            r.update({"ok": False, "reason": "sudah tercatat (referensi sama)", "duplicate": True})
        if r.get("ok"):
            running += float(r.get("amount") or 0)
            if running - avail > 0.01:
                r.update({"ok": False, "reason": f"melebihi saldo platform ({_rp(avail)}) — catat dana dilepas dulu"})
    return rows


def _new_doc(account: dict, user, withdrawal_date: str, amount: float, reference: str, notes: str) -> dict:
    doc = {
        "id": str(uuid.uuid4()), "account_id": account["id"], "withdrawal_date": withdrawal_date,
        "amount": round(float(amount), 2), "reference": (reference or "").strip() or None, "notes": notes or "",
        "je_id": None, "je_number": None, "je_status": None,
        "bank_txn_id": None, "bank_session_id": None, "bank_txn_date": None,
        "created_by": user.get("email") if isinstance(user, dict) else None,
        "created_at": _now(), "updated_at": _now(),
    }
    _scope.stamp_account(doc, account)
    if not doc["reference"]:
        doc["reference"] = f"WD-{(doc.get('platform') or 'X').upper()[:3]}-{withdrawal_date.replace('-', '')}-{doc['id'][:6].upper()}"
    return doc


@router.post("/import/preview")
async def import_preview(request: Request, file: UploadFile = File(...), account_id: str = Form(default=""),
                         mapping: str = Form(default="")):
    """Baca laporan penarikan Shopee/TikTok → DRAF baris. TIDAK menyimpan apa pun.
    `mapping` (JSON {role: header}) opsional bila staf mengganti kolom yang dipakai."""
    await _require_finance(request)
    db = get_db()
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Berkas kosong.")
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "Berkas melebihi 15 MB.")
    fname = file.filename or "penarikan.csv"
    if not fname.lower().endswith((".csv", ".xlsx", ".xls", ".xlsm", ".tsv", ".txt")):
        raise HTTPException(415, "Hanya CSV atau Excel (.xlsx) yang didukung.")
    mp = None
    if mapping:
        import json
        try:
            mp = json.loads(mapping)
        except ValueError:
            raise HTTPException(400, "Format pemetaan kolom tidak valid.")
    try:
        parsed = _wimport.parse_withdrawal_report(raw, fname, mp)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Berkas tidak bisa dibaca: {e}")
    if account_id:
        account = await _scope.require_account(db, account_id)
        parsed["rows"] = await _annotate_rows(db, account, parsed["rows"])
        parsed["available_balance"] = await _bal.available_balance(db, account_id)
        parsed["cash_code"] = (account.get("coa_cash_code") or "").strip() or None
    parsed["total_ok"] = round(sum(r["amount"] or 0 for r in parsed["rows"] if r["ok"]), 2)
    parsed["ok_count"] = sum(1 for r in parsed["rows"] if r["ok"])
    return {"ok": True, **parsed}


@router.post("/import/commit")
async def import_commit(body: ImportCommitIn, request: Request):
    """Simpan baris penarikan hasil pratinjau yang DIPILIH staf. Duplikat referensi dilewati,
    saldo dicek kumulatif — tidak ada baris yang membuat saldo platform minus."""
    user = await _require_finance(request)
    db = get_db()
    account = await _scope.require_account(db, body.account_id)
    if not body.rows:
        raise HTTPException(400, "Tidak ada baris yang dipilih.")
    rows = [{"withdrawal_date": r.withdrawal_date, "amount": round(float(r.amount), 2),
             "reference": (r.reference or "").strip() or None, "ok": True, "reason": None} for r in body.rows]
    rows = await _annotate_rows(db, account, rows)
    created, skipped = [], []
    for r in rows:
        if not r["ok"]:
            skipped.append({"reference": r["reference"], "amount": r["amount"], "reason": r["reason"]})
            continue
        doc = _new_doc(account, user, r["withdrawal_date"], r["amount"], r["reference"] or "",
                       f"Impor {body.filename or 'laporan penarikan'}")
        await db[COLL].insert_one(doc)
        created.append(_ser(doc))
    return {"ok": True, "created": created, "skipped": skipped,
            "created_count": len(created), "skipped_count": len(skipped),
            "created_total": round(sum(c["amount"] for c in created), 2),
            "message": f"{len(created)} penarikan tercatat"
                       + (f", {len(skipped)} dilewati" if skipped else "") + "."}


async def _coa_for(db, account: dict) -> dict:
    recv = _bal.receivable_code(account)
    cash = (account.get("coa_cash_code") or "").strip()
    missing = []
    if not recv:
        missing.append("Akun Saldo Platform / Piutang Toko (`ar_account_code`)")
    if not cash:
        missing.append("Rekening Pencairan (`coa_cash_code`)")
    for code in (recv, cash):
        if code:
            acc = await db.rahaza_coa_accounts.find_one(
                {"code": code}, {"_id": 0, "is_group": 1, "active": 1})
            if not acc or acc.get("is_group") or not acc.get("active", True):
                missing.append(f"akun `{code}` tidak ada/tidak aktif/akun induk")
    if missing:
        raise HTTPException(
            400, f"Toko '{account.get('account_name')}' belum siap dijurnal: {'; '.join(missing)}. "
                 f"Isi dulu di Portal Marketing → Kelola Akun (Tautan Finance).")
    return {"receivable": recv, "cash": cash}


async def _check_balance(db, account: dict, amount: float, exclude_id: str = ""):
    avail = await _bal.available_balance(db, account["id"], exclude_id)
    if amount - avail > 0.01:
        raise HTTPException(
            400, f"Penarikan {_rp(amount)} melebihi saldo platform toko "
                 f"'{account.get('account_name')}' yang tercatat ({_rp(avail)}). Catat dulu "
                 f"laporan dana dilepas (Penghasilan/Settlement) yang belum masuk — saldo tidak "
                 f"boleh minus.")
    return avail


@router.get("")
async def list_withdrawals(
    request: Request,
    account_id: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=200),
):
    user = await require_auth(request)
    db = get_db()
    q: dict = {}
    vis = await _scope.visible_account_ids(db, user)
    if vis is not None:
        q["account_id"] = {"$in": vis}
    if account_id:
        q["account_id"] = account_id
    if date_from:
        q.setdefault("withdrawal_date", {})["$gte"] = date_from
    if date_to:
        q.setdefault("withdrawal_date", {})["$lte"] = date_to
    total = await db[COLL].count_documents(q)
    rows = await db[COLL].find(q, {"_id": 0}).sort("withdrawal_date", -1) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    agg = await db[COLL].aggregate([
        {"$match": q}, {"$group": {"_id": None, "amount": {"$sum": "$amount"}}}]).to_list(1)
    linked = await db[COLL].count_documents({**q, "bank_txn_id": {"$nin": [None, ""]}})
    return {
        "ok": True, "data": [_ser(r) for r in rows],
        "summary": {"amount": round(float((agg[0] if agg else {}).get("amount") or 0), 2),
                    "bank_linked_count": linked, "bank_unlinked_count": total - linked},
        "pagination": {"total": total, "page": page, "page_size": page_size,
                       "total_pages": max(1, (total + page_size - 1) // page_size)},
    }


@router.post("")
async def create_withdrawal(body: WithdrawalIn, request: Request):
    user = await _require_finance(request)
    db = get_db()
    account = await _scope.require_account(db, body.account_id)
    ref = (body.reference or "").strip()
    if ref and await db[COLL].find_one({"account_id": body.account_id, "reference": ref}, {"_id": 0, "id": 1}):
        raise HTTPException(409, f"Penarikan '{ref}' untuk toko ini sudah pernah dicatat.")
    await _check_balance(db, account, body.amount)
    doc = _new_doc(account, user, body.withdrawal_date, body.amount, ref, body.notes or "")
    await db[COLL].insert_one(doc)
    return {"ok": True, "data": _ser(doc)}


@router.put("/{wid}")
async def update_withdrawal(wid: str, body: WithdrawalIn, request: Request):
    await _require_finance(request)
    db = get_db()
    cur = await db[COLL].find_one({"id": wid}, {"_id": 0})
    if not cur:
        raise HTTPException(404, "Penarikan tidak ditemukan.")
    if await _je_still_binding(db, cur):
        raise HTTPException(400, f"Penarikan ini sudah punya jurnal ({cur.get('je_number')}). "
                                 f"Void jurnalnya dulu di Portal Finance sebelum mengubah angkanya.")
    if cur.get("bank_txn_id") and round(float(body.amount), 2) != round(float(cur.get("amount") or 0), 2):
        raise HTTPException(400, f"Nominal sudah TERTAUT ke mutasi bank tanggal {cur.get('bank_txn_date')} "
                                 f"({_rp(cur.get('amount'))}). Lepas tautannya di Rekonsiliasi Bank dulu.")
    account = await _scope.require_account(db, body.account_id)
    await _check_balance(db, account, body.amount, exclude_id=wid)
    upd = body.dict()
    upd.update({"amount": round(float(body.amount), 2), "reference": (body.reference or "").strip() or cur.get("reference"),
                "updated_at": _now()})
    if cur.get("je_id"):
        upd.update({"je_id": None, "je_number": None, "je_status": None, "je_voided_ref": cur.get("je_number")})
    _scope.stamp_account(upd, account)
    await db[COLL].update_one({"id": wid}, {"$set": upd})
    return {"ok": True, "data": _ser({**cur, **upd})}


@router.delete("/{wid}")
async def delete_withdrawal(wid: str, request: Request):
    await _require_finance(request)
    db = get_db()
    cur = await db[COLL].find_one({"id": wid}, {"_id": 0})
    if not cur:
        raise HTTPException(404, "Penarikan tidak ditemukan.")
    if await _je_still_binding(db, cur):
        raise HTTPException(400, f"Tidak bisa dihapus: sudah terbit jurnal {cur.get('je_number')}. Void dulu.")
    if cur.get("bank_txn_id"):
        raise HTTPException(400, f"Tidak bisa dihapus: sudah tertaut ke mutasi bank tanggal "
                                 f"{cur.get('bank_txn_date')}. Lepas tautannya di Rekonsiliasi Bank dulu.")
    await db[COLL].delete_one({"id": wid})
    return {"ok": True}


@router.post("/{wid}/journal")
async def create_draft_journal(wid: str, request: Request):
    """Dr Bank toko / Cr Piutang Toko — DRAFT, idempoten per `reference`."""
    user = await _require_finance(request)
    db = get_db()
    doc = await db[COLL].find_one({"id": wid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Penarikan tidak ditemukan.")
    account = await _scope.require_account(db, doc["account_id"])
    coa = await _coa_for(db, account)

    from routes.rahaza_posting import _create_posted_je, _find_existing_je

    existing = await _find_existing_je(db, SOURCE_MODULE, doc["reference"])
    if existing:
        await db[COLL].update_one({"id": wid}, {"$set": {
            "je_id": existing["id"], "je_number": existing["je_number"],
            "je_status": existing["status"], "updated_at": _now()}})
        return {"ok": True, "already": True, "je_number": existing["je_number"],
                "je_status": existing["status"],
                "message": f"Penarikan ini sudah punya jurnal {existing['je_number']} ({existing['status']})."}

    amt = round(float(doc["amount"]), 2)
    lines = [
        {"account_code": coa["cash"], "debit": amt, "credit": 0,
         "description": f"Penarikan saldo {doc['platform']} ke bank ({doc['reference']})"},
        {"account_code": coa["receivable"], "debit": 0, "credit": amt,
         "description": f"Saldo platform {doc.get('account_name') or ''} ditarik"},
    ]
    res = await _create_posted_je(
        db, je_date=date.fromisoformat(str(doc["withdrawal_date"])[:10]),
        memo=f"Penarikan saldo {doc['platform']} — {doc.get('account_name') or ''} ({doc['reference']})",
        source_module=SOURCE_MODULE, source_ref=doc["reference"],
        lines_raw=lines, user=user, status="draft")
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "Gagal membuat jurnal.")
    await db[COLL].update_one({"id": wid}, {"$set": {
        "je_id": res["je_id"], "je_number": res["je_number"], "je_status": "draft",
        "coa_used": coa, "updated_at": _now()}})
    return {"ok": True, "je_id": res["je_id"], "je_number": res["je_number"], "je_status": "draft",
            "coa_used": coa,
            "message": f"Jurnal DRAFT {res['je_number']} dibuat: Dr {coa['cash']} / Cr {coa['receivable']}. "
                       f"Tekan 'Posting' setelah dicek."}


@router.post("/{wid}/post")
async def post_withdrawal_journal(wid: str, request: Request):
    user = await _require_finance(request)
    db = get_db()
    doc = await db[COLL].find_one({"id": wid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Penarikan tidak ditemukan.")
    if not doc.get("je_id"):
        raise HTTPException(400, "Penarikan ini belum punya jurnal draf. Tekan 'Buat jurnal' dulu.")

    from routes.rahaza_journals import _check_period_open, _mirror_lines

    je = await db.rahaza_journal_entries.find_one({"id": doc["je_id"]})
    if not je:
        raise HTTPException(404, f"Jurnal {doc.get('je_number')} sudah tidak ada.")
    if je.get("status") == "posted":
        await db[COLL].update_one({"id": wid}, {"$set": {"je_status": "posted"}})
        return {"ok": True, "already": True, "je_number": je["je_number"], "je_status": "posted",
                "message": f"Jurnal {je['je_number']} sudah diposting."}
    if je.get("status") != "draft":
        raise HTTPException(400, f"Hanya jurnal draf yang bisa diposting. Status sekarang: {je.get('status')}.")
    await _check_period_open(db, date.fromisoformat(str(je["date"])[:10]))
    await db.rahaza_journal_entries.update_one(
        {"id": je["id"]},
        {"$set": {"status": "posted", "posted_at": _now(), "posted_by": (user or {}).get("id"), "updated_at": _now()}})
    je["status"] = "posted"
    await _mirror_lines(db, je)
    await db[COLL].update_one({"id": wid}, {"$set": {"je_status": "posted", "updated_at": _now()}})
    return {"ok": True, "je_number": je["je_number"], "je_status": "posted",
            "message": f"Jurnal {je['je_number']} diposting ke buku besar."}
