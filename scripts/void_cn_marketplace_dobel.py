#!/usr/bin/env python3
"""Batalkan jurnal Credit Note retur MARKETPLACE lama yang dulu tercatat dobel (Iter 122).

Latar: sebelum Iter 121, CN dari modul Retur Marketing dijurnal Dr 4-1200 / Cr Piutang
MARKETPLACE, padahal nilai refund sudah diakui lewat baris `refunds` jurnal pencairan
marketplace → 4-1200 dobel. Skrip ini:
  1. mencari rahaza_credit_notes yang punya `return_id` (asal retur marketing) dan gl_je_id terisi,
  2. me-void JE-nya (status voided + hapus cermin rahaza_journal_lines) bila periodenya masih terbuka,
  3. menandai CN gl_mode='settlement' (gl_je_id None, simpan gl_voided_je_number utk audit),
  4. menonaktifkan pelanggan fiktif MARKETPLACE bila tidak dipakai invoice AR.

Default DRY-RUN. Jalankan dengan --apply untuk mengeksekusi.
    cd /app/backend && python3 ../scripts/void_cn_marketplace_dobel.py [--apply]
"""
import asyncio
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

REASON = "Void otomatis Iter 122: CN retur marketplace dobel dengan baris refunds pencairan (4-1200)."


async def main(apply: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    from routes.rahaza_posting import _ensure_period_open

    cns = await db.rahaza_credit_notes.find(
        {"return_id": {"$exists": True, "$ne": None}, "gl_je_id": {"$nin": [None, ""]}},
        {"_id": 0}).to_list(5000)
    print(f"[cn-dobel] mode={'APPLY' if apply else 'DRY-RUN'} · kandidat CN marketplace berjurnal: {len(cns)}")
    voided, skipped, total_amt = 0, [], 0.0
    now = datetime.now(timezone.utc)
    for cn in cns:
        err = None
        je = await db.rahaza_journal_entries.find_one({"id": cn["gl_je_id"]}, {"_id": 0})
        label = f"{cn.get('cn_number')} → {(je or {}).get('je_number')} Rp {round(float(cn.get('total') or 0)):,}"
        if not je:
            skipped.append((label, "JE tidak ditemukan"))
        elif je.get("status") == "voided":
            skipped.append((label, "JE sudah voided"))
        else:
            err = await _ensure_period_open(db, date.fromisoformat(je["date"]))
            if err:
                skipped.append((label, f"periode terkunci: {err}"))
                continue
            total_amt += float(cn.get("total") or 0)
            voided += 1
            print(f"  VOID  {label}")
            if apply:
                await db.rahaza_journal_entries.update_one({"id": je["id"]}, {"$set": {
                    "status": "voided", "voided_at": now, "voided_by": "script:void_cn_marketplace_dobel",
                    "void_reason": REASON, "updated_at": now}})
                await db.rahaza_journal_lines.delete_many({"je_id": je["id"]})
        if apply and (not je or je.get("status") == "voided" or not err):
            await db.rahaza_credit_notes.update_one({"id": cn["id"]}, {"$set": {
                "gl_mode": "settlement", "gl_je_id": None, "gl_je_number": None, "gl_posted_at": None,
                "gl_voided_je_number": (je or {}).get("je_number"), "gl_voided_at": now,
                "gl_note": "Retur marketplace diakui lewat baris refunds pada jurnal pencairan — jurnal lama di-void (Iter 122)."}})
    for label, why in skipped:
        print(f"  SKIP  {label} · {why}")

    mkt = await db.rahaza_customers.find_one({"code": "MARKETPLACE"}, {"_id": 0, "id": 1, "active": 1})
    if mkt and mkt.get("active", True):
        used = await db.rahaza_ar_invoices.count_documents({"customer_id": mkt["id"]})
        if used == 0:
            print("  NONAKTIFKAN pelanggan fiktif MARKETPLACE (tidak dipakai invoice AR)")
            if apply:
                await db.rahaza_customers.update_one({"id": mkt["id"]}, {"$set": {"active": False, "updated_at": now}})
        else:
            print(f"  BIARKAN pelanggan MARKETPLACE (dipakai {used} invoice AR)")

    print(f"[cn-dobel] selesai · void={voided} (Rp {round(total_amt):,}) · skip={len(skipped)}"
          + ("" if apply else " · DRY-RUN, tambahkan --apply untuk eksekusi"))


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
