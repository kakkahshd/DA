"""Perbaikan data dev: invoice AR SL-20260905-002 gagal posting (diskon, subtotal bruto) → repost & selaraskan sub-akun."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


async def main():
    from database import get_db
    from routes.rahaza_posting import post_ar_invoice
    db = get_db()
    user = await db.users.find_one({"email": "admin@garment.com"}, {"_id": 0}) or {"id": "system", "name": "system"}
    for note in await db.sales_direct_notes.find({"ar_invoice_id": {"$ne": None}, "ar_je_id": None}, {"_id": 0}).to_list(100):
        inv = await db.rahaza_ar_invoices.find_one({"id": note["ar_invoice_id"]}, {"_id": 0})
        if not inv:
            continue
        net = float(note["subtotal"]) - float(note.get("discount_amount") or 0)
        await db.rahaza_ar_invoices.update_one({"id": inv["id"]}, {"$set": {"subtotal": net}})
        inv["subtotal"] = net
        res = await post_ar_invoice(db, inv, user)
        print(note["note_number"], res)
        if res.get("ok"):
            await db.sales_direct_notes.update_one({"id": note["id"]}, {"$set": {"ar_je_id": res["je_id"], "ar_post_error": None}})
            inv2 = await db.rahaza_ar_invoices.find_one({"id": inv["id"]}, {"_id": 0, "gl_ar_account_code": 1})
            sub = inv2.get("gl_ar_account_code")
            if sub and sub != "1-1301":
                # jurnal pembayaran/CN/refund yang tadinya jatuh ke kontrol → pindah ke sub-akun pelanggan
                refs = [f"cn:{c['id']}" for c in await db.rahaza_credit_notes.find({"ar_invoice_id": inv["id"]}, {"id": 1}).to_list(50)]
                movs = [m["id"] for m in await db.rahaza_cash_movements.find({"ref_id": inv["id"]}, {"id": 1}).to_list(50)]
                rets = [f"refund:{r['id']}" for r in await db.sales_direct_returns.find({"ar_invoice_id": inv["id"]}, {"id": 1}).to_list(50)]
                jes = await db.rahaza_journal_entries.find({"$or": [{"source_ref": {"$in": refs + rets}},
                                                                    {"source_module": "ar_payment", "source_ref": {"$regex": "|".join(movs) or "^$"}}]}, {"id": 1, "lines": 1}).to_list(100)
                for je in jes:
                    lines = [{**l, "account_code": sub} if l["account_code"] == "1-1301" else l for l in je["lines"]]
                    await db.rahaza_journal_entries.update_one({"id": je["id"]}, {"$set": {"lines": lines}})
                    await db.rahaza_journal_lines.update_many({"je_id": je["id"], "account_code": "1-1301"}, {"$set": {"account_code": sub}})
                print("  sub-akun diselaraskan:", sub, len(jes), "JE")


asyncio.run(main())
