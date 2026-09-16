#!/usr/bin/env python3
"""scripts/audit_data_demo.py — INVENTARISASI data demo/uji di basis data (READ-ONLY).

    python3 scripts/audit_data_demo.py            # ringkasan ke layar
    python3 scripts/audit_data_demo.py --json out.json

Tidak menghapus apa pun. Hasilnya menjadi bahan keputusan owner sebelum
`scripts/reset_for_golive.py`. Dokumen master yang sudah punya turunan transaksi
ditandai — meniru pendekatan `core/cut_panel_health.REFERENCE_CHECKS`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEMO_PREFIXES = ("DEMO-", "CTH-", "PO-MK-DEMO-", "SJ-MK-DEMO-", "JOB-MK-DEMO-", "VFH6B-",
                 "PO-INT-DEMO-", "UJI", "TEST-")
CODE_FIELDS = ("code", "sku", "po_number", "shipment_number", "job_number", "employee_code",
               "account_code", "creator_code", "email")
KEY_COLLECTIONS = ("rahaza_materials", "rahaza_models", "rahaza_boms", "rahaza_locations",
                   "rahaza_employees", "users", "marketing_catalog_items", "dewi_maklon_pos",
                   "production_pos", "po_items", "production_jobs", "vendor_shipments",
                   "vendor_partners", "marketing_platform_accounts")
# (koleksi master, koleksi turunan, field rujukan) — master yang dirujuk tidak boleh
# dihapus sendiri-sendiri tanpa turunannya ikut dibersihkan.
REFERENCE_CHECKS = (
    ("rahaza_materials", "rahaza_material_stock", "material_id"),
    ("rahaza_materials", "rahaza_stock_ledger", "material_id"),
    ("rahaza_materials", "rahaza_boms", "materials.material_id"),
    ("rahaza_models", "production_pos", "items.model_id"),
    ("rahaza_models", "po_items", "model_id"),
    ("rahaza_employees", "rahaza_attendance", "employee_id"),
    ("rahaza_employees", "rahaza_payroll_profiles", "employee_id"),
    ("rahaza_locations", "rahaza_material_stock", "location_id"),
    ("vendor_partners", "production_pos", "vendor_id"),
    ("vendor_partners", "vendor_shipments", "vendor_id"),
    ("marketing_platform_accounts", "marketing_orders", "account_id"),
    ("marketing_platform_accounts", "marketing_catalog_items", "account_id"),
)


def _is_demo_code(doc: dict) -> bool:
    for f in CODE_FIELDS:
        v = str(doc.get(f) or "").upper()
        if v and v.startswith(DEMO_PREFIXES):
            return True
    return False


async def audit(db) -> dict:
    names = sorted(await db.list_collection_names())
    report = {"collections": {}, "referenced_masters": {}, "totals": {"documents": 0, "demo_flagged": 0}}
    for name in names:
        total = await db[name].count_documents({})
        if not total:
            continue
        marked = await db[name].count_documents({"$or": [
            {"import_source": {"$exists": True}}, {"import_batch": {"$exists": True}},
            {"created_by": "seed"}, {"seed": True}, {"is_demo": True}]})
        demo_codes = 0
        if name in KEY_COLLECTIONS or total <= 5000:
            async for d in db[name].find({}, {"_id": 0, **{f: 1 for f in CODE_FIELDS}}):
                if _is_demo_code(d):
                    demo_codes += 1
        report["collections"][name] = {"total": total, "bertanda_import_seed": marked,
                                       "kode_demo": demo_codes, "kunci": name in KEY_COLLECTIONS}
        report["totals"]["documents"] += total
        report["totals"]["demo_flagged"] += demo_codes
    for master, child, field in REFERENCE_CHECKS:
        try:
            ids = [d["id"] async for d in db[master].find({}, {"_id": 0, "id": 1}) if d.get("id")]
            if not ids:
                continue
            n = await db[child].count_documents({field: {"$in": ids}})
        except Exception:  # noqa: BLE001 — koleksi boleh tidak ada
            n = 0
        if n:
            report["referenced_masters"].setdefault(master, []).append(
                {"turunan": child, "field": field, "dokumen": n})
    users = [u async for u in db.users.find({}, {"_id": 0, "email": 1, "role": 1, "status": 1})]
    report["users"] = [{"email": re.sub(r"(^.).*(@.*$)", r"\1***\2", u.get("email", "")),
                        "role": u.get("role"), "status": u.get("status")} for u in users]
    return report


def print_report(rep: dict) -> None:
    print(f"{'KOLEKSI':40s} {'TOTAL':>7s} {'IMPORT/SEED':>12s} {'KODE DEMO':>10s}")
    for name, c in rep["collections"].items():
        flag = " *" if c["kunci"] else ""
        print(f"{name:40s} {c['total']:7d} {c['bertanda_import_seed']:12d} {c['kode_demo']:10d}{flag}")
    print(f"\nTotal dokumen: {rep['totals']['documents']}  · berkode demo: {rep['totals']['demo_flagged']}")
    print("\nMASTER YANG SUDAH PUNYA TURUNAN TRANSAKSI (jangan dihapus sendiri-sendiri):")
    if not rep["referenced_masters"]:
        print("  (tidak ada)")
    for m, refs in rep["referenced_masters"].items():
        for r in refs:
            print(f"  {m:28s} ← {r['turunan']} ({r['field']}): {r['dokumen']} dok")
    print("\nAKUN LOGIN (email disamarkan):")
    for u in rep["users"]:
        print(f"  {u['email']:32s} {u['role']:20s} {u['status']}")


async def main(json_out: Path | None) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    from motor.motor_asyncio import AsyncIOMotorClient
    from master_review_safety import ReadOnlyDatabase
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        real = client[os.environ["DB_NAME"]]
        db = ReadOnlyDatabase(real)
        db.list_collection_names = real.list_collection_names
        rep = await audit(db)
    finally:
        client.close()
    print_report(rep)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
        print(f"\nLaporan JSON: {json_out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(Path(a.json) if a.json else None)))
