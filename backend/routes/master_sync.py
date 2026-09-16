"""Sinkron master produk lintas portal (varian SSOT ∪ BOM ∪ FG, style RnD, karyawan↔user) — lihat core/master_sync."""
from fastapi import APIRouter, Request

from auth import log_activity
from core.master_sync import sync_product_masters
from database import get_db
from routes.rahaza_coa import _require_fin

router = APIRouter(prefix="/api/rahaza/master", tags=["master-sync"])


@router.post("/sync")
async def run_master_sync(request: Request):
    user = await _require_fin(request)
    report = await sync_product_masters(get_db(), user)
    await log_activity(user["id"], user.get("name", ""), "master_sync", "master", str(report)[:400])
    return report
