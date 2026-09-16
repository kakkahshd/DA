"""Peringatan harga bahan & upah PO internal — supaya lapisan HPP tidak lahir bernilai nol."""
from fastapi import APIRouter, HTTPException, Request

from auth import require_auth
from database import get_db
from routes.production_rbac import deny_klien

router = APIRouter(prefix="/api", tags=["production-pos"])


@router.get("/production-pos/{po_id}/cost-check")
async def po_cost_check(po_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "id": 1, "po_number": 1, "business_type": 1, "po_type": 1})
    if not po:
        raise HTTPException(404, "PO tidak ditemukan")
    from core.fg_cost_layers import compute_batch_unit_cost
    items = await db.po_items.find({"po_id": po_id}, {"_id": 0}).to_list(None)
    rows, warn = [], 0
    for it in items:
        qty = int(float(it.get("qty") or 0) or 1)
        c = await compute_batch_unit_cost(db, po_item=it, qty=qty)
        issues = []
        if c["material_source"] == "none" or c["material_cost"] <= 0:
            issues.append("harga bahan kosong (BOM/harga master belum ada)")
        if c["sewing_cost"] <= 0:
            issues.append("upah jahit/pcs belum diisi")
        issues += [g for g in c.get("gaps", []) if "belum punya harga" in g]
        warn += 1 if issues else 0
        rows.append({"po_item_id": it.get("id"), "sku": it.get("sku"), "product_name": it.get("product_name"), "qty": it.get("qty"),
                     "material_cost": c["material_cost"], "sewing_cost": c["sewing_cost"], "unit_cost": c["unit_cost"],
                     "issues": issues, "gaps": c.get("gaps", [])})
    return {"po_id": po_id, "po_number": po.get("po_number"), "items": rows, "items_with_issues": warn, "ok": warn == 0,
            "estimated_batch_value": round(sum(r["unit_cost"] * float(r.get("qty") or 0) for r in rows), 2)}
