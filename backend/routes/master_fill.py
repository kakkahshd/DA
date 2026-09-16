"""Jalan pintas pengisian master: salin BOM ke varian, tambah aksesoris massal, template Harga·Satuan·Rekening, HPP standar."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from auth import log_activity
from core import master_fill as mf
from database import get_db
from routes.rahaza_coa import _require_fin

router = APIRouter(prefix="/api/rahaza/master", tags=["master-fill"])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Berkas harus .xlsx (template dari layar ini).")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Berkas terlalu besar (maks 8 MB).")
    return data


@router.post("/bom/copy-missing")
async def bom_copy_missing(request: Request):
    user = await _require_fin(request)
    body = await request.json() if (request.headers.get("content-length") or "0") != "0" else {}
    res = await mf.bom_copy_to_missing(get_db(), user, body.get("model_id"))
    await log_activity(user["id"], user.get("name", ""), "bom_copy_missing", "rahaza.bom", f"{res['created']} BOM baru")
    return res


@router.post("/bom/add-lines")
async def bom_add_lines(request: Request):
    user = await _require_fin(request)
    body = await request.json()
    if not body.get("model_id") or not body.get("lines"):
        raise HTTPException(400, "model_id & lines wajib diisi.")
    res = await mf.bom_add_lines_to_model(get_db(), user, body["model_id"], body["lines"])
    await log_activity(user["id"], user.get("name", ""), "bom_add_lines", "rahaza.bom", f"{body['model_id']} +{res['lines_appended']}")
    return res


@router.get("/fill-template")
async def fill_template(request: Request):
    await _require_fin(request)
    data = await mf.build_fill_template(get_db())
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX, headers={"Content-Disposition": 'attachment; filename="TEMPLATE_HARGA_SATUAN_REKENING.xlsx"'})


@router.post("/fill-preview")
async def fill_preview(request: Request, file: UploadFile = File(...)):
    await _require_fin(request)
    return await mf.parse_fill_workbook(get_db(), await _read(file))


@router.post("/fill-apply")
async def fill_apply(request: Request, file: UploadFile = File(...)):
    user = await _require_fin(request)
    db = get_db()
    parsed = await mf.parse_fill_workbook(db, await _read(file))
    if not parsed["ok"]:
        raise HTTPException(400, {"message": "Berkas belum lolos pemeriksaan.", "errors": parsed["errors"]})
    res = await mf.apply_fill(db, parsed, user)
    await log_activity(user["id"], user.get("name", ""), "fill_apply", "master", str(res)[:300])
    return res


@router.post("/recalc-hpp")
async def recalc_hpp(request: Request):
    user = await _require_fin(request)
    return await mf.recalc_standard_costs(get_db(), user)
