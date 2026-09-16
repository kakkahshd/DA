"""core.cut_panel_master — SSOT master POTONGAN (kain pola) & baris BOM potongan.

KEPUTUSAN OWNER 2026-09-12
--------------------------
BOM produk TIDAK lagi menyebut kain roll (0,465 kg/pcs) — angka itu menyesatkan
("dari mana 0,53 kg itu?"). Baris kain diganti **1 pcs POTONGAN** per pcs baju:
  * 1 master potongan per model × warna × ukuran, kode `CUT-<MODEL>-<WARNA>-<UKURAN>`
    (contoh `CUT-DA-2101-CRL-ALLSIZE`, satuan pcs, `is_cut_panel: true`).
  * Biaya potongan = nilai kain roll yang benar-benar dipotong ÷ pcs potongan jadi
    (Portal Cutting, rata-rata bergerak). Contoh owner: roll 150 yard Rp 3.000.000 →
    150 potongan → Rp 20.000/potongan. Inilah dasar HPP bahan produk.
  * Sebelum ada hasil cutting nyata, HPP bahan JUJUR Rp 0 + peringatan (tidak ditebak).
  * Rencana pemakaian kain di Portal Cutting diisi manual (tidak disimpan di BOM).

Modul ini dipakai oleh: Portal Cutting (output order), importir 10_BOM, skrip migrasi
BOM kain→potongan, dan kalkulator HPP (penanda baris potongan).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

PANEL_UNIT = "pcs"
PANEL_CATEGORY = "POTONGAN"
PANEL_CATEGORY_NAME = "Potongan / Kain Pola"


def _now():
    return datetime.now(timezone.utc)


def slug(v: str, maxlen: int = 24) -> str:
    out = "".join(ch for ch in (v or "").upper() if ch.isalnum() or ch in (" ", "-"))
    out = "-".join(p for p in out.replace(" ", "-").split("-") if p)
    return out[:maxlen] or "NA"


def panel_code(model_code: str, color_code: str, size_code: str) -> str:
    parts = [slug(model_code), slug(color_code or "", 10), slug(size_code or "", 8)]
    return "CUT-" + "-".join(p for p in parts if p and p != "NA")


def panel_name(model_name: str, color_name: str, size_code: str) -> str:
    parts = [p for p in [model_name or "Potongan", color_name, size_code] if p]
    return "Potongan " + " · ".join(parts)


def is_panel_material(mat: dict | None) -> bool:
    return bool(mat and (mat.get("is_cut_panel") or str(mat.get("code") or "").upper().startswith("CUT-")))


def is_panel_line(line: dict | None) -> bool:
    return bool(line and (line.get("is_cut_panel") or str(line.get("code") or "").upper().startswith("CUT-")))


async def resolve_color(db, *, color_id: str | None = None, color: str | None = None) -> tuple[str, str]:
    """(kode, nama) warna master dari id ATAU kode/nama (tanpa peduli huruf besar)."""
    doc = None
    if color_id:
        doc = await db.rahaza_colors.find_one({"id": color_id}, {"_id": 0, "code": 1, "name": 1})
    if not doc and color:
        c = color.strip()
        doc = await db.rahaza_colors.find_one(
            {"$or": [{"code": {"$regex": f"^{c}$", "$options": "i"}},
                     {"name": {"$regex": f"^{c}$", "$options": "i"}}]},
            {"_id": 0, "code": 1, "name": 1})
    if doc:
        return (doc.get("code") or "").upper(), doc.get("name") or ""
    return slug(color or "", 10) if color else "", color or ""


async def find_panel(db, *, model_id: str, color_code: str, size_code: str, code: str | None = None):
    q = {"is_cut_panel": True, "active": True, "model_id": model_id,
         "color_code": (color_code or "").upper(), "size_code": (size_code or "").upper()}
    doc = await db.rahaza_materials.find_one(q, {"_id": 0})
    if doc:
        return doc
    if code:
        return await db.rahaza_materials.find_one({"code": code, "active": True}, {"_id": 0})
    return None


def build_panel_doc(*, model: dict, color_code: str, color_name: str, size_code: str,
                    size_id: str | None, source_fabric: dict | None, created_from: str,
                    cutting_order: dict | None = None) -> dict:
    src = source_fabric or {}
    code = panel_code(model.get("code") or "", color_code, size_code)
    o = cutting_order or {}
    return {
        "id": str(uuid.uuid4()),
        "code": code,
        "name": panel_name(model.get("name") or model.get("code") or "", color_name or color_code, size_code),
        "type": "fabric",
        "unit": PANEL_UNIT,
        "category": PANEL_CATEGORY,
        "category_name": PANEL_CATEGORY_NAME,
        "color": color_name or color_code or "",
        "color_code": (color_code or "").upper(),
        "composition": src.get("composition") or "",
        "notes": (f"Potongan {model.get('code')} — sumber kain {src.get('code') or '-'}"
                  + (f" · lahir dari Cutting {o.get('number')}" if o.get("number") else "")),
        "min_stock": 0,
        "unit_cost": 0.0,
        "value_status": "unvalued",
        "value_note": "Belum ada hasil cutting nyata — biaya lahir saat kain roll dipotong (nilai kain ÷ pcs).",
        "base_uom": PANEL_UNIT,
        "uoms": [{"code": PANEL_UNIT, "name": "PCS", "factor": 1.0, "is_base": True, "level": 0}],
        "purchase_uom": PANEL_UNIT, "issue_uom": PANEL_UNIT, "display_uom": PANEL_UNIT,
        "pack_unit": "pack", "pack_size": 1, "display_in_packs": False,
        "is_cut_panel": True,
        "source_material_id": src.get("id"),
        "source_material_code": src.get("code") or "",
        "model_id": model.get("id"),
        "model_code": model.get("code") or "",
        "style_sku": model.get("code") or "",
        "style_name": model.get("name") or "",
        "size": size_code or "",
        "size_code": (size_code or "").upper(),
        "size_id": size_id or "",
        "cutting_order_id": o.get("id") or "",
        "cutting_order_number": o.get("number") or "",
        "created_from": created_from,
        "active": True,
        "created_at": _now(), "updated_at": _now(),
    }


async def ensure_panel(db, *, model: dict, color_code: str, color_name: str, size_code: str,
                       size_id: str | None = None, source_fabric: dict | None = None,
                       created_from: str = "bom", cutting_order: dict | None = None,
                       apply: bool = True) -> tuple[dict, bool]:
    """Pakai-ulang / buat master potongan (idempoten). Mengembalikan (doc, created)."""
    code = panel_code(model.get("code") or "", color_code, size_code)
    existing = await find_panel(db, model_id=model.get("id"), color_code=color_code,
                                size_code=size_code, code=code)
    if existing:
        patch = {}
        for k, v in (("model_id", model.get("id")), ("model_code", model.get("code") or ""),
                     ("color_code", (color_code or "").upper()), ("size_code", (size_code or "").upper()),
                     ("size_id", size_id or existing.get("size_id") or "")):
            if v and existing.get(k) != v:
                patch[k] = v
        if source_fabric and not existing.get("source_material_id"):
            patch["source_material_id"] = source_fabric.get("id")
            patch["source_material_code"] = source_fabric.get("code") or ""
        if patch and apply:
            patch["updated_at"] = _now()
            await db.rahaza_materials.update_one({"id": existing["id"]}, {"$set": patch})
            existing.update(patch)
        return existing, False
    doc = build_panel_doc(model=model, color_code=color_code, color_name=color_name, size_code=size_code,
                          size_id=size_id, source_fabric=source_fabric, created_from=created_from,
                          cutting_order=cutting_order)
    if apply:
        await db.rahaza_materials.insert_one(dict(doc))
    return doc, True


def bom_line_for_panel(panel: dict, fabric_line: dict | None = None) -> dict:
    """Baris BOM '1 pcs potongan'. Jejak kain asal disimpan hanya untuk audit (bukan biaya)."""
    line = {
        "material_id": panel["id"], "code": panel["code"], "name": panel["name"],
        "material_type": "fabric", "category_name": PANEL_CATEGORY_NAME,
        "qty": 1.0, "unit": PANEL_UNIT, "qty_base": 1.0, "unit_base": PANEL_UNIT,
        "uom_factor": 1.0, "uom_status": "base", "uom_note": "",
        "unit_cost_base": float(panel.get("unit_cost") or 0),
        "is_cut_panel": True,
        "source_material_code": panel.get("source_material_code") or "",
        "notes": (fabric_line or {}).get("notes") or "",
    }
    if fabric_line:
        line["source_row"] = fabric_line.get("source_row")
        line["migrated_from_fabric"] = {
            "code": fabric_line.get("code"), "qty": fabric_line.get("qty_base") or fabric_line.get("qty"),
            "unit": fabric_line.get("unit_base") or fabric_line.get("unit"),
            "note": "jejak audit — bukan dasar HPP (keputusan owner 2026-09-12)",
        }
    return line
