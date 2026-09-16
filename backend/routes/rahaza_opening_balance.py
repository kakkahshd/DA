"""Saldo Awal Neraca Go-Live — layar Master Akuntansi (unduh template · pratinjau · posting · status).
Logika di core/opening_balance.py (dipakai juga scripts/saldo_awal_golive.py)."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import log_activity, serialize_doc
from core import opening_balance as ob
from database import get_db
from routes.rahaza_coa import _require_fin

router = APIRouter(prefix="/api/rahaza/finance/opening-balance", tags=["rahaza-opening-balance"])
_MAX = 5 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Berkas harus .xlsx (template yang diunduh dari layar ini).")
    data = await file.read()
    if len(data) > _MAX:
        raise HTTPException(400, "Berkas terlalu besar (maks 5 MB).")
    return data


@router.get("/status")
async def status(request: Request):
    await _require_fin(request)
    db = get_db()
    je = await ob.existing_opening(db)
    acc_count = await db.rahaza_coa_accounts.count_documents({"active": True, "type": {"$in": list(ob.BALANCE_TYPES)}, "is_group": False})
    lines = []
    if je:
        full = await db.rahaza_journal_entries.find_one({"id": je["id"]}, {"_id": 0, "lines": 1})
        lines = (full or {}).get("lines") or []
    return {"journal": serialize_doc(je) if je else None, "lines": lines, "balance_accounts": acc_count,
            "relation_sheets": [{"sheet": s, "control_account": c} for s, c, _ in ob.RELATION_SHEETS]}


@router.get("/template")
async def template(request: Request):
    await _require_fin(request)
    data, n = await ob.build_template(get_db())
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="SALDO_AWAL_GOLIVE.xlsx"', "X-Account-Count": str(n)})


@router.post("/preview")
async def preview(request: Request, file: UploadFile = File(...), balance_to_retained: bool = Form(False)):
    await _require_fin(request)
    db = get_db()
    res = await ob.parse_workbook(db, await _read(file), balance_to_retained)
    res["existing"] = serialize_doc(await ob.existing_opening(db))
    res["filename"] = file.filename
    return res


@router.post("/apply")
async def apply(request: Request, file: UploadFile = File(...), ob_date: str = Form(...), balance_to_retained: bool = Form(False)):
    user = await _require_fin(request)
    db = get_db()
    res = await ob.parse_workbook(db, await _read(file), balance_to_retained)
    if not res["ok"]:
        raise HTTPException(400, {"message": "Berkas belum lolos pemeriksaan — perbaiki dulu.", "errors": res["errors"]})
    je = await ob.post_opening(db, user, ob_date, res["lines"], file.filename or "upload")
    await log_activity(user["id"], user.get("name", ""), "post_opening_balance", "journal", f"{je['je_number']} {ob_date} {len(res['lines'])} baris")
    return {"ok": True, "journal": serialize_doc(je), "totals": res["totals"]}
