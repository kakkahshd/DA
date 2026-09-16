"""Portal Penjualan — Penjualan Langsung dari stok barang jadi (FG internal).

Satu nota = stok FG keluar (FIFO, `production_qty_ledger.issue_fg`) + jurnal COGS
(Dr 5-xxxx / Cr 1-1404) + invoice AR kanonik (`rahaza_ar_invoices`, source_module
`direct_sale`) + (tunai) penerimaan kas. Semua jurnal lewat mesin posting yang sudah ada.
"""
import io
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pymongo import ReturnDocument

from auth import log_activity, require_auth, serialize_doc
from database import get_db
from routes.shared import require_portal_dep
from utils.counters import gen_prefixed_number

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sales", tags=["sales-direct"],
                   dependencies=[Depends(require_portal_dep("sales"))])

COLL = "sales_direct_notes"
RET = "sales_direct_returns"
WRITE_ROLES = ("superadmin", "admin", "owner", "accounting", "staff_keuangan", "manager_keuangan",
               "sales", "admin_sales", "pic_toko", "cs_staff", "manager_marketing", "admin_gudang")
TERMS_DAYS = {"cash": 0, "net_7": 7, "net_14": 14, "net_30": 30}


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


def _num(v, field="nilai"):
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} harus berupa angka.")
    if f < 0:
        raise HTTPException(400, f"{field} tidak boleh negatif.")
    return f


async def _require_write(request: Request):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    perms = user.get("_permissions") or []
    if role in WRITE_ROLES or "*" in perms or "sales.manage" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh hak membuat penjualan.")


# ── MASTER PELANGGAN (SSOT rahaza_customers) ─────────────────────────────────
@router.get("/customers")
async def list_customers(request: Request, include_inactive: bool = False):
    await require_auth(request)
    db = get_db()
    q = {} if include_inactive else {"active": {"$ne": False}}
    rows = await db.rahaza_customers.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    return serialize_doc(rows)


@router.post("/customers")
async def create_customer(request: Request):
    user = await _require_write(request)
    db = get_db()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nama pelanggan wajib.")
    code = (body.get("code") or "").strip().upper()
    from core.doc_number_policy import issue_number
    code = await issue_number(db, "rahaza_customers.code", requested=code)
    if await db.rahaza_customers.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah terpakai.")
    doc = {
        "id": _uid(), "code": code, "name": name,
        "company_type": body.get("company_type") or "personal",
        "npwp": (body.get("npwp") or "").strip(), "phone": (body.get("phone") or "").strip(),
        "email": (body.get("email") or "").strip(), "address": body.get("address") or "",
        "payment_terms": body.get("payment_terms") or "cash",
        "credit_limit": _num(body.get("credit_limit"), "credit_limit"),
        "notes": body.get("notes") or "", "active": True,
        "created_at": _now(), "updated_at": _now(), "created_by": user.get("id"),
    }
    await db.rahaza_customers.insert_one(doc)
    try:
        from routes.coa_auto import ensure_subledger_for_entity
        await ensure_subledger_for_entity(db, "customer", doc, user)
    except Exception as e:  # noqa: BLE001
        log.error("[sales] subledger piutang gagal utk %s: %s", code, e)
    await log_activity(user["id"], user.get("name", ""), "create", "sales.customer", code)
    return serialize_doc(await db.rahaza_customers.find_one({"id": doc["id"]}, {"_id": 0}))


@router.put("/customers/{cid}")
async def update_customer(cid: str, request: Request):
    user = await _require_write(request)
    db = get_db()
    body = await request.json()
    upd = {k: body[k] for k in ("name", "company_type", "npwp", "phone", "email", "address",
                                "payment_terms", "notes", "active") if k in body}
    if "credit_limit" in body:
        upd["credit_limit"] = _num(body.get("credit_limit"), "credit_limit")
    upd["updated_at"] = _now()
    res = await db.rahaza_customers.update_one({"id": cid}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, "Pelanggan tidak ditemukan.")
    await log_activity(user["id"], user.get("name", ""), "update", "sales.customer", cid)
    return serialize_doc(await db.rahaza_customers.find_one({"id": cid}, {"_id": 0}))


@router.delete("/customers/{cid}")
async def deactivate_customer(cid: str, request: Request):
    await _require_write(request)
    db = get_db()
    await db.rahaza_customers.update_one({"id": cid}, {"$set": {"active": False, "updated_at": _now()}})
    return {"status": "deactivated"}


# ── STOK FG YANG BISA DIJUAL ──────────────────────────────────────────────────
async def _fg_available_map(db, material_ids: Optional[list] = None) -> dict:
    match = {"inventory_category": "fg_internal"}
    if material_ids is not None:
        match["material_id"] = {"$in": material_ids}
    rows = await db.rahaza_material_stock.aggregate([
        {"$match": match},
        {"$group": {"_id": "$material_id", "qty": {"$sum": {"$ifNull": ["$qty", 0]}}}},
    ]).to_list(20000)
    return {r["_id"]: float(r.get("qty") or 0) for r in rows if r.get("_id")}


@router.get("/fg-stock")
async def fg_stock(request: Request, q: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    avail = await _fg_available_map(db)
    ids = [k for k, v in avail.items() if v > 0]
    if not ids:
        return []
    mats = await db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "code": 1, "sku": 1, "name": 1,
                                                                  "hpp": 1, "hpp_source": 1, "hpp_fifo_avg": 1}).to_list(20000)
    cats = await db.marketing_catalog_items.find({"fg_product_id": {"$in": ids}},
                                                 {"_id": 0, "fg_product_id": 1, "selling_price": 1, "price": 1}).to_list(20000)
    price_map = {c["fg_product_id"]: float(c.get("selling_price") or c.get("price") or 0) for c in cats}
    out = []
    ql = (q or "").lower()
    for m in mats:
        if ql and ql not in (m.get("code") or "").lower() and ql not in (m.get("name") or "").lower():
            continue
        out.append({"material_id": m["id"], "sku": m.get("code") or m.get("sku") or "", "name": m.get("name") or "",
                    "available_qty": avail.get(m["id"], 0), "hpp": float(m.get("hpp_fifo_avg") or m.get("hpp") or 0),
                    "hpp_source": m.get("hpp_source") or "none", "default_price": price_map.get(m["id"], 0)})
    out.sort(key=lambda r: r["sku"])
    return out


# ── NOTA PENJUALAN LANGSUNG ───────────────────────────────────────────────────
def _calc(items, tax_pct, discount):
    subtotal = sum(i["amount"] for i in items)
    if discount > subtotal:
        raise HTTPException(400, "Diskon melebihi nilai nota.")
    tax = round((subtotal - discount) * tax_pct / 100)  # PPN atas nilai setelah diskon
    total = round(subtotal - discount + tax)
    return round(subtotal), tax, total


@router.post("/direct-sales")
async def create_direct_sale(request: Request):
    user = await _require_write(request)
    db = get_db()
    body = await request.json()
    cust = await db.rahaza_customers.find_one({"id": body.get("customer_id")}, {"_id": 0})
    if not cust:
        raise HTTPException(400, "Pelanggan wajib dipilih (master pelanggan).")
    payment_type = body.get("payment_type") or "cash"
    if payment_type not in ("cash", "credit"):
        raise HTTPException(400, "payment_type harus cash|credit.")
    raw_items = body.get("items") or []
    if not raw_items:
        raise HTTPException(400, "Minimal satu item.")
    ids = [i.get("material_id") for i in raw_items if i.get("material_id")]
    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1})}
    avail = await _fg_available_map(db, ids)
    items, want = [], {}
    for idx, it in enumerate(raw_items):
        m = mats.get(it.get("material_id"))
        if not m:
            raise HTTPException(400, f"Item ke-{idx + 1}: SKU FG tidak ditemukan.")
        qty = int(_num(it.get("qty"), "qty"))
        price = _num(it.get("price"), "harga")
        if qty <= 0:
            raise HTTPException(400, f"Item ke-{idx + 1}: qty harus > 0.")
        want[m["id"]] = want.get(m["id"], 0) + qty
        if want[m["id"]] > avail.get(m["id"], 0):
            raise HTTPException(400, f"Stok {m.get('code')} tidak cukup (tersedia {int(avail.get(m['id'], 0))}, diminta {want[m['id']]}).")
        items.append({"material_id": m["id"], "sku": m.get("code") or "", "name": m.get("name") or "",
                      "qty": qty, "price": price, "amount": round(qty * price)})
    tax_pct = _num(body.get("tax_pct"), "tax_pct")
    discount = _num(body.get("discount_amount"), "discount_amount")
    subtotal, tax, total = _calc(items, tax_pct, discount)
    sale_date = body.get("sale_date") or date.today().isoformat()
    if payment_type == "cash":
        if not body.get("cash_account_id"):
            raise HTTPException(400, "Rekening kas/bank wajib untuk penjualan tunai.")
        if not await db.rahaza_cash_accounts.find_one({"id": body["cash_account_id"]}):
            raise HTTPException(404, "Rekening kas tidak ditemukan.")
        due_date = sale_date
    else:
        days = TERMS_DAYS.get(cust.get("payment_terms") or "", 30)
        due_date = body.get("due_date") or (date.fromisoformat(sale_date) + timedelta(days=days or 30)).isoformat()
    doc = {
        "id": _uid(), "note_number": await gen_prefixed_number(db, COLL, "note_number", f"SL-{sale_date.replace('-', '')}-", 3),
        "customer_id": cust["id"], "customer_name": cust.get("name"), "customer_code": cust.get("code"),
        "sale_date": sale_date, "due_date": due_date, "payment_type": payment_type,
        "cash_account_id": body.get("cash_account_id") if payment_type == "cash" else None,
        "items": items, "subtotal": subtotal, "tax_pct": tax_pct, "tax_amount": tax,
        "discount_amount": round(discount), "total": total,
        "status": "draft", "notes": body.get("notes") or "",
        "created_at": _now(), "updated_at": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", ""),
    }
    await db[COLL].insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "sales.direct", doc["note_number"])
    return serialize_doc(doc)


async def _apply_ar_payment(db, inv_id: str, amount: float, cash_account_id: str, pay_date: str, user: dict, notes: str = ""):
    """Terima pembayaran AR: update invoice atomik + kas + jurnal (pola rahaza_finance.record_ar_payment)."""
    from routes.rahaza_posting import post_ar_invoice, post_ar_payment
    acc = await db.rahaza_cash_accounts.find_one({"id": cash_account_id}, {"_id": 0})
    if not acc:
        raise HTTPException(404, "Rekening kas tidak ditemukan.")
    updated = await db.rahaza_ar_invoices.find_one_and_update(
        {"id": inv_id, "status": {"$nin": ["cancelled", "void", "written_off"]},
         "$expr": {"$lte": [{"$add": [{"$ifNull": ["$paid_amount", 0]}, amount]}, {"$add": [{"$ifNull": ["$total", 0]}, 0.01]}]}},
        [{"$set": {
            "paid_amount": {"$round": [{"$add": [{"$ifNull": ["$paid_amount", 0]}, amount]}, 0]},
            "balance": {"$max": [0, {"$round": [{"$subtract": [{"$ifNull": ["$total", 0]}, {"$add": [{"$ifNull": ["$paid_amount", 0]}, amount]}]}, 0]}]},
            "status": {"$cond": [{"$gte": [{"$add": [{"$ifNull": ["$paid_amount", 0]}, amount]}, {"$subtract": [{"$ifNull": ["$total", 0]}, 0.01]}]}, "paid", "partial_paid"]},
            "updated_at": _now()}},
         {"$set": {"total_amount": {"$ifNull": ["$total", 0]}, "amount_paid": "$paid_amount", "amount_due": "$balance"}}],
        return_document=ReturnDocument.AFTER)
    if not updated:
        raise HTTPException(400, "Pembayaran melebihi sisa tagihan atau invoice sudah ditutup.")
    movement_id = _uid()
    await db.rahaza_cash_movements.insert_one({
        "id": movement_id, "account_id": cash_account_id, "account_name": acc.get("name"), "direction": "in",
        "amount": round(amount), "category": "ar_payment", "ref_id": inv_id, "ref_label": updated.get("invoice_number"),
        "date": pay_date, "notes": notes, "timestamp": _now(), "created_by": user["id"], "created_by_name": user.get("name", "")})
    if not updated.get("gl_je_id"):
        await post_ar_invoice(db, updated, user)
        updated = await db.rahaza_ar_invoices.find_one({"id": inv_id}, {"_id": 0})
    posting = await post_ar_payment(db, updated, amount, cash_account_id, pay_date, user, movement_id=movement_id)
    return {"invoice": await db.rahaza_ar_invoices.find_one({"id": inv_id}, {"_id": 0}), "movement_id": movement_id, "posting": posting}


async def _post_cogs(db, note: dict, issued_rows: list, user: dict) -> dict:
    from routes.rahaza_posting import _create_posted_je, _fifo_rows_to_components, _find_existing_je
    from routes.rahaza_posting_profiles import get_mapping
    source_ref = f"cogs_sale:{note['id']}"
    existing = await _find_existing_je(db, "cogs_direct_sale", source_ref)
    if existing:
        return {"ok": True, "je_id": existing["id"], "je_number": existing["je_number"], "already_posted": True}
    mapping = await get_mapping(db, "cogs_shipment")
    dm, dl, do, cfg = (mapping.get(k) for k in ("debit_cogs_material", "debit_cogs_labor", "debit_cogs_overhead", "credit_fg_inventory"))
    if not all([dm, dl, do, cfg]):
        return {"ok": False, "error": "Mapping 'cogs_shipment' belum lengkap."}
    fifo = await _fifo_rows_to_components(db, issued_rows)
    # Fallback JUJUR (seperti post_cogs_shipment): pcs tanpa lapisan biaya memakai HPP master (perkiraan), diberi label.
    est_total, est_rows = 0.0, []
    for r in issued_rows:
        if r.get("fg_cogs_uncosted_qty") and r.get("material_id"):
            m = await db.rahaza_materials.find_one({"id": r["material_id"]}, {"_id": 0, "hpp": 1})
            hpp = float((m or {}).get("hpp") or 0)
            if hpp > 0:
                est = round(hpp * int(r["fg_cogs_uncosted_qty"]), 2)
                est_total += est
                r["fg_cogs_estimated"] = est
                est_rows.append(f"{r['sku']}: {r['fg_cogs_uncosted_qty']} pcs × HPP master Rp {hpp:,.0f}")
    total = round(fifo["total"] + est_total, 2)
    basis = "fifo_batch" if fifo["total"] > 0 and not est_total else ("hpp_master" if not fifo["total"] and est_total else "mixed")
    if total <= 0:
        return {"ok": False, "reason": "zero_cogs", "uncosted_qty": fifo["uncosted_qty"], "basis": basis,
                "error": "COGS = 0: barang keluar tanpa lapisan biaya batch dan tanpa HPP master — HPP tidak bisa dibukukan."}
    label = {"fifo_batch": "biaya batch FIFO", "hpp_master": "perkiraan HPP master", "mixed": "FIFO + perkiraan HPP master"}[basis]
    memo = f"COGS Penjualan Langsung {note['note_number']} ({label})"
    lines = []
    for code, amt, lbl in ((dm, fifo["material"] + est_total, "Material"), (dl, fifo["labor"], "Labor"), (do, fifo["overhead"], "Overhead")):
        if amt > 0:
            lines.append({"account_code": code, "debit": round(amt, 2), "credit": 0, "description": f"{memo} - {lbl}"})
    lines.append({"account_code": cfg, "debit": 0, "credit": total, "description": f"{memo} - FG Inventory"})
    res = await _create_posted_je(db, date.fromisoformat(note["sale_date"]), memo, "cogs_direct_sale", source_ref, lines, user)
    res.update({"total_cogs": total, "fifo_cogs": round(fifo["total"], 2), "estimated_cogs": round(est_total, 2), "basis": basis,
                "uncosted_qty": fifo["uncosted_qty"], "gaps": fifo["gaps"] + est_rows})
    return res


@router.post("/direct-sales/{sid}/confirm")
async def confirm_direct_sale(sid: str, request: Request):
    user = await _require_write(request)
    db = get_db()
    from core.production_qty_ledger import FGStockShortfall, issue_fg
    from routes.rahaza_posting import post_ar_invoice
    note = await db[COLL].find_one_and_update({"id": sid, "status": "draft"}, {"$set": {"status": "confirming", "updated_at": _now()}},
                                              projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if not note:
        cur = await db[COLL].find_one({"id": sid}, {"_id": 0, "status": 1})
        if not cur:
            raise HTTPException(404, "Nota tidak ditemukan.")
        raise HTTPException(400, f"Nota berstatus '{cur.get('status')}' tidak bisa dikonfirmasi.")
    # cek stok dulu supaya tidak keluar separuh
    avail = await _fg_available_map(db, [i["material_id"] for i in note["items"]])
    need = {}
    for it in note["items"]:
        need[it["material_id"]] = need.get(it["material_id"], 0) + it["qty"]
    short = [f"{it['sku']} (tersedia {int(avail.get(it['material_id'], 0))}, perlu {need[it['material_id']]})"
             for it in note["items"] if need[it["material_id"]] > avail.get(it["material_id"], 0)]
    if short:
        await db[COLL].update_one({"id": sid}, {"$set": {"status": "draft"}})
        raise HTTPException(400, "Stok tidak cukup: " + "; ".join(sorted(set(short))))

    ref = {"type": "direct_sale", "id": sid, "note_number": note["note_number"], "doc": "sales_direct_notes"}
    issued_rows, total_uncosted = [], 0
    try:
        for it in note["items"]:
            r = await issue_fg(db, material_id=it["material_id"], qty=it["qty"], ref=ref, actor=user, sku=it["sku"])
            it["fg_cogs"] = float(r.get("cogs") or 0)
            it["fg_cogs_layers"] = r.get("cogs_layers") or []
            it["fg_cogs_uncosted_qty"] = int(r.get("uncosted_qty") or 0)
            total_uncosted += it["fg_cogs_uncosted_qty"]
            issued_rows.append({"material_id": it["material_id"], "sku": it["sku"], "qty_shipped": it["qty"], "fg_cogs": it["fg_cogs"],
                                "fg_cogs_layers": it["fg_cogs_layers"], "fg_cogs_uncosted_qty": it["fg_cogs_uncosted_qty"]})
    except FGStockShortfall as e:
        await db[COLL].update_one({"id": sid}, {"$set": {"status": "draft", "items": note["items"]}})
        raise HTTPException(400, f"Stok tidak cukup saat pengeluaran: {e}")

    from routes.rahaza_finance import _gen_number
    invoice_number = await _gen_number(db, "rahaza_ar_invoices", "AR")
    inv = {
        "id": _uid(), "invoice_number": invoice_number, "customer_id": note["customer_id"], "customer_name": note["customer_name"],
        "order_id": None, "issue_date": note["sale_date"], "due_date": note["due_date"],
        "items": [{"description": f"{i['sku']} {i['name']}".strip(), "qty": i["qty"], "unit": "pcs", "price": i["price"], "amount": i["amount"]} for i in note["items"]],
        # Konvensi AR kanonik (post_ar_invoice): `subtotal` = SETELAH diskon; revenue bruto = subtotal + discount_amount
        "subtotal": note["subtotal"] - note["discount_amount"], "tax_pct": note["tax_pct"], "tax_amount": note["tax_amount"], "discount_amount": note["discount_amount"],
        "total": note["total"], "paid_amount": 0, "balance": note["total"],
        "total_amount": note["total"], "amount_paid": 0, "amount_due": note["total"],
        "status": "issued", "notes": f"Penjualan langsung {note['note_number']}", "sales_channel": "direct",
        "source_module": "direct_sale", "direct_sale_id": sid, "created_at": _now(), "updated_at": _now(),
        "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_ar_invoices.insert_one(inv)
    inv.pop("_id", None)
    ar_post = await post_ar_invoice(db, inv, user)
    cogs_post = await _post_cogs(db, note, issued_rows, user)
    for it, r in zip(note["items"], issued_rows):
        if r.get("fg_cogs_estimated"):
            it["fg_cogs_estimated"] = r["fg_cogs_estimated"]
    upd = {"status": "confirmed", "items": note["items"], "ar_invoice_id": inv["id"], "invoice_number": invoice_number,
           "ar_je_id": ar_post.get("je_id"), "ar_post_error": ar_post.get("error"),
           "cogs_total": round(float(cogs_post.get("total_cogs") or 0), 2), "cogs_basis": cogs_post.get("basis"),
           "cogs_estimated": round(float(cogs_post.get("estimated_cogs") or 0), 2), "cogs_je_id": cogs_post.get("je_id"),
           "cogs_je_number": cogs_post.get("je_number"), "cogs_post_error": cogs_post.get("error"),
           "uncosted_qty": total_uncosted, "confirmed_at": _now(), "confirmed_by": user.get("name", ""), "updated_at": _now()}
    payment = None
    if note["payment_type"] == "cash":
        try:
            payment = await _apply_ar_payment(db, inv["id"], float(note["total"]), note["cash_account_id"], note["sale_date"], user,
                                              notes=f"Tunai {note['note_number']}")
            upd["status"] = "paid"
            upd["paid_amount"] = note["total"]
            upd["payment_je_id"] = (payment.get("posting") or {}).get("je_id")
        except HTTPException as e:
            upd["payment_error"] = e.detail
    await db[COLL].update_one({"id": sid}, {"$set": upd})
    await log_activity(user["id"], user.get("name", ""), "confirm", "sales.direct", note["note_number"])
    out = await db[COLL].find_one({"id": sid}, {"_id": 0})
    out["_ar_posting"] = ar_post
    out["_cogs_posting"] = cogs_post
    return serialize_doc(out)


@router.post("/direct-sales/{sid}/payment")
async def pay_direct_sale(sid: str, request: Request):
    user = await _require_write(request)
    db = get_db()
    body = await request.json()
    note = await db[COLL].find_one({"id": sid}, {"_id": 0})
    if not note or not note.get("ar_invoice_id"):
        raise HTTPException(404, "Nota belum dikonfirmasi / tidak ditemukan.")
    amount = _num(body.get("amount"), "amount")
    if amount <= 0:
        raise HTTPException(400, "amount harus > 0.")
    if not body.get("cash_account_id"):
        raise HTTPException(400, "Rekening kas wajib.")
    res = await _apply_ar_payment(db, note["ar_invoice_id"], amount, body["cash_account_id"], body.get("date") or date.today().isoformat(), user,
                                  notes=body.get("notes") or f"Pelunasan {note['note_number']}")
    inv = res["invoice"]
    await db[COLL].update_one({"id": sid}, {"$set": {"paid_amount": inv.get("paid_amount"), "status": "paid" if inv.get("status") == "paid" else "confirmed",
                                                     "updated_at": _now()}})
    return serialize_doc({"note": await db[COLL].find_one({"id": sid}, {"_id": 0}), "invoice": inv, "posting": res["posting"]})


@router.post("/direct-sales/{sid}/cancel")
async def cancel_direct_sale(sid: str, request: Request):
    user = await _require_write(request)
    db = get_db()
    res = await db[COLL].find_one_and_update({"id": sid, "status": "draft"},
                                             {"$set": {"status": "cancelled", "cancelled_at": _now(), "cancelled_by": user.get("name", ""), "updated_at": _now()}},
                                             projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if not res:
        raise HTTPException(400, "Hanya nota draft yang bisa dibatalkan (nota terkonfirmasi sudah mengurangi stok & berjurnal).")
    return serialize_doc(res)


@router.get("/direct-sales")
async def list_direct_sales(request: Request, status: Optional[str] = None, customer_id: Optional[str] = None, limit: int = 300):
    await require_auth(request)
    db = get_db()
    q = {}
    if status:
        q["status"] = status
    if customer_id:
        q["customer_id"] = customer_id
    rows = await db[COLL].find(q, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 1000))
    inv_ids = [r["ar_invoice_id"] for r in rows if r.get("ar_invoice_id")]
    invs = {i["id"]: i async for i in db.rahaza_ar_invoices.find({"id": {"$in": inv_ids}}, {"_id": 0, "id": 1, "status": 1, "balance": 1, "paid_amount": 1})} if inv_ids else {}
    for r in rows:
        i = invs.get(r.get("ar_invoice_id")) or {}
        r["ar_status"] = i.get("status")
        r["ar_balance"] = i.get("balance")
    return serialize_doc(rows)


@router.get("/direct-sales/{sid}")
async def get_direct_sale(sid: str, request: Request):
    await require_auth(request)
    db = get_db()
    note = await db[COLL].find_one({"id": sid}, {"_id": 0})
    if not note:
        raise HTTPException(404, "Nota tidak ditemukan.")
    if note.get("ar_invoice_id"):
        note["invoice"] = await db.rahaza_ar_invoices.find_one({"id": note["ar_invoice_id"]}, {"_id": 0})
        note["payments"] = await db.rahaza_cash_movements.find({"ref_id": note["ar_invoice_id"], "category": "ar_payment"}, {"_id": 0}).sort("timestamp", 1).to_list(100)
    note["returns"] = await db[RET].find({"direct_sale_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return serialize_doc(note)


@router.get("/dashboard")
async def sales_dashboard(request: Request):
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    month = today[:7]
    rows = await db[COLL].find({"status": {"$in": ["confirmed", "paid"]}}, {"_id": 0, "sale_date": 1, "total": 1, "cogs_total": 1, "items": 1,
                                                                          "status": 1, "payment_type": 1, "ar_invoice_id": 1}).to_list(5000)
    inv_ids = [r["ar_invoice_id"] for r in rows if r.get("ar_invoice_id")]
    invs = {i["id"]: i async for i in db.rahaza_ar_invoices.find({"id": {"$in": inv_ids}}, {"_id": 0, "id": 1, "balance": 1, "status": 1, "due_date": 1})} if inv_ids else {}
    out = {"today_sales": 0.0, "today_count": 0, "month_sales": 0.0, "month_count": 0, "month_cogs": 0.0,
           "open_ar": 0.0, "open_ar_count": 0, "overdue_ar": 0.0, "overdue_count": 0, "top_skus": [], "draft_count": 0}
    sku_acc = {}
    for r in rows:
        if r.get("sale_date") == today:
            out["today_sales"] += float(r.get("total") or 0)
            out["today_count"] += 1
        if (r.get("sale_date") or "")[:7] == month:
            out["month_sales"] += float(r.get("total") or 0)
            out["month_cogs"] += float(r.get("cogs_total") or 0)
            out["month_count"] += 1
            for it in r.get("items") or []:
                s = sku_acc.setdefault(it["sku"], {"sku": it["sku"], "name": it.get("name"), "qty": 0, "amount": 0.0})
                s["qty"] += it.get("qty") or 0
                s["amount"] += float(it.get("amount") or 0)
        inv = invs.get(r.get("ar_invoice_id")) or {}
        bal = float(inv.get("balance") or 0)
        if bal > 0 and inv.get("status") not in ("cancelled", "written_off"):
            out["open_ar"] += bal
            out["open_ar_count"] += 1
            if (inv.get("due_date") or today) < today:
                out["overdue_ar"] += bal
                out["overdue_count"] += 1
    out["draft_count"] = await db[COLL].count_documents({"status": "draft"})
    out["month_gross_margin"] = round(out["month_sales"] - out["month_cogs"], 2)
    out["top_skus"] = sorted(sku_acc.values(), key=lambda s: -s["amount"])[:5]
    for k in ("today_sales", "month_sales", "month_cogs", "open_ar", "overdue_ar"):
        out[k] = round(out[k], 2)
    return out


@router.get("/cash-accounts")
async def cash_accounts(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_cash_accounts.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "type": 1, "bank_name": 1}).to_list(200)
    return serialize_doc(rows)


# ── CETAK NOTA (PDF) — mengikuti template PDF pemilik (doc_key `sales-note`) ──
def _rp(n) -> str:
    return "Rp " + f"{int(round(float(n or 0))):,}".replace(",", ".")


def _fmt_d(s):
    try:
        dt = datetime.strptime((s or "")[:10], "%Y-%m-%d")
        return f"{dt.day} {['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agt', 'Sep', 'Okt', 'Nov', 'Des'][dt.month - 1]} {dt.year}"
    except ValueError:
        return s or "-"


def build_sales_note_pdf(*, note: dict, customer: dict, template: dict, profile: dict, printed_by: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle

    from core.pdf_template import apply_columns, column_weights, footer_flowables, header_flowables, signature_flowables
    from data.pdf_doc_registry import columns_of, weights_of
    from routes.operations_pdf_helpers import CONTENT_W_PORTRAIT, _build_pdf, _pdf_data_table

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#1f2937"))
    muted = ParagraphStyle("muted", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#64748b"))
    right = ParagraphStyle("right", parent=body, alignment=2)
    avail = CONTENT_W_PORTRAIT
    status_lbl = {"draft": "DRAFT", "confirmed": "BELUM LUNAS", "paid": "LUNAS", "cancelled": "BATAL"}.get(note.get("status"), (note.get("status") or "").upper())
    pay_lbl = "TUNAI" if note.get("payment_type") == "cash" else f"TEMPO · JT {_fmt_d(note.get('due_date'))}"
    elems = header_flowables(template.get("header"), profile, template.get("title") or "NOTA PENJUALAN", avail=avail,
                             info_pairs=[("No. Nota", note.get("note_number")), ("Tanggal", _fmt_d(note.get("sale_date"))),
                                         ("No. Invoice", note.get("invoice_number") or "-"), ("Pembayaran", f"{pay_lbl} · {status_lbl}")])
    bill = (f"<b>Kepada:</b><br/>{customer.get('name') or note.get('customer_name') or '-'}"
            f"<br/><font size=8 color='#64748b'>{customer.get('address') or ''}<br/>{customer.get('phone') or ''}"
            f"{(' · ' + customer['email']) if customer.get('email') else ''}{('<br/>NPWP ' + customer['npwp']) if customer.get('npwp') else ''}</font>")
    elems += [Paragraph(bill, body), Spacer(1, 4 * mm)]

    all_cols = columns_of("sales-note")
    rows = [[str(i), it.get("sku") or "", it.get("name") or "-", str(it.get("qty") or 0), "pcs", _rp(it.get("price")), _rp(it.get("amount"))]
            for i, it in enumerate(note.get("items") or [], start=1)]
    tpl_cols = template.get("columns") or []
    headers, rows2, keys = apply_columns(tpl_cols, [c["key"] for c in all_cols], [c["label"] for c in all_cols], rows)
    elems.append(_pdf_data_table(headers, rows2, weights=column_weights(tpl_cols, keys, weights_of("sales-note")),
                                 right_cols=[i for i, k in enumerate(keys) if k in ("qty", "price", "amount")], style=template.get("table")))
    elems.append(Spacer(1, 4 * mm))

    totals = [["Subtotal", _rp(note.get("subtotal"))]]
    if (note.get("tax_amount") or 0) > 0:
        totals.append([f"PPN ({int(note.get('tax_pct') or 0)}%)", _rp(note.get("tax_amount"))])
    if (note.get("discount_amount") or 0) > 0:
        totals.append(["Diskon", "-" + _rp(note.get("discount_amount"))])
    totals.append(["<b>Total</b>", "<b>" + _rp(note.get("total")) + "</b>"])
    inv = note.get("invoice") or {}
    if inv:
        totals.append(["Sudah Dibayar", _rp(inv.get("paid_amount"))])
        totals.append(["<b>Sisa Tagihan</b>", "<b>" + _rp(inv.get("balance")) + "</b>"])
    if note.get("returned_total"):
        totals.append(["Retur / Nota Kredit", "-" + _rp(note.get("returned_total"))])
    tt = Table([[Paragraph(k, right), Paragraph(v, right)] for k, v in totals], colWidths=[avail * 0.24, avail * 0.20])
    tt.setStyle(TableStyle([("LINEABOVE", (0, len(totals) - (3 if inv else 1)), (-1, len(totals) - (3 if inv else 1)), 0.6, colors.HexColor("#94a3b8")),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    wrap = Table([["", tt]], colWidths=[avail * 0.56, avail * 0.44])
    wrap.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elems.append(wrap)
    if note.get("notes"):
        elems += [Spacer(1, 3 * mm), Paragraph(f"<b>Catatan:</b> {note['notes']}", muted)]
    elems.extend(signature_flowables(template.get("signatures"), {
        "customer_name": customer.get("name") or note.get("customer_name") or "", "note_number": note.get("note_number") or "",
        "invoice_number": note.get("invoice_number") or "", "confirmed_by": note.get("confirmed_by") or note.get("created_by_name") or "",
        "printed_by": printed_by}, avail=avail))
    elems += [Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#cbd5e1")),
              Paragraph("Barang yang sudah dibeli dapat diretur sesuai kesepakatan dengan menyertakan nota ini.", muted)]
    elems.extend(footer_flowables(template.get("footer"), profile))
    return _build_pdf(io.BytesIO(), elems, page=template.get("page")).getvalue()


@router.get("/direct-sales/{sid}/pdf")
async def direct_sale_pdf(sid: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    note = await db[COLL].find_one({"id": sid}, {"_id": 0})
    if not note:
        raise HTTPException(404, "Nota tidak ditemukan.")
    cust = await db.rahaza_customers.find_one({"id": note["customer_id"]}, {"_id": 0}) or {}
    if note.get("ar_invoice_id"):
        note["invoice"] = await db.rahaza_ar_invoices.find_one({"id": note["ar_invoice_id"]}, {"_id": 0, "paid_amount": 1, "balance": 1}) or {}
    from core import pdf_template
    template = await pdf_template.resolve(db, "sales-note")
    profile = await pdf_template.company_profile(db)
    pdf = build_sales_note_pdf(note=note, customer=cust, template=template, profile=profile, printed_by=user.get("name") or "")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Nota_{note["note_number"]}.pdf"'})


# ── RETUR PENJUALAN (nota kredit + stok kembali + balik HPP) ──────────────────
def _ratio_lines(je: Optional[dict]) -> dict:
    """Proporsi komponen COGS (material/labor/overhead) dari JE COGS asal — utk membalik HPP ke akun yang sama."""
    out = {}
    for l in (je or {}).get("lines") or []:
        if float(l.get("debit") or 0) > 0:
            out[l["account_code"]] = out.get(l["account_code"], 0) + float(l["debit"])
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()} if tot else {}


@router.post("/direct-sales/{sid}/returns")
async def create_return(sid: str, request: Request):
    user = await _require_write(request)
    db = get_db()
    body = await request.json()
    note = await db[COLL].find_one({"id": sid}, {"_id": 0})
    if not note:
        raise HTTPException(404, "Nota tidak ditemukan.")
    if note.get("status") not in ("confirmed", "paid"):
        raise HTTPException(400, "Retur hanya untuk nota yang sudah dikonfirmasi.")
    raw = body.get("items") or []
    if not raw:
        raise HTTPException(400, "Minimal satu item retur.")
    prev = await db[RET].find({"direct_sale_id": sid, "status": {"$ne": "cancelled"}}, {"_id": 0, "items": 1}).to_list(200)
    returned = {}
    for r in prev:
        for it in r["items"]:
            returned[it["material_id"]] = returned.get(it["material_id"], 0) + it["qty"]
    sold = {it["material_id"]: it for it in note["items"]}
    items = []
    for idx, ri in enumerate(raw):
        src = sold.get(ri.get("material_id"))
        if not src:
            raise HTTPException(400, f"Item ke-{idx + 1} tidak ada di nota.")
        qty = int(_num(ri.get("qty"), "qty"))
        if qty <= 0:
            raise HTTPException(400, f"Item ke-{idx + 1}: qty harus > 0.")
        left = src["qty"] - returned.get(src["material_id"], 0)
        if qty > left:
            raise HTTPException(400, f"{src['sku']}: maksimal retur {left} pcs (terjual {src['qty']}, sudah diretur {returned.get(src['material_id'], 0)}).")
        unit_cost = round((float(src.get("fg_cogs") or 0) + float(src.get("fg_cogs_estimated") or 0)) / src["qty"], 2) if src["qty"] else 0
        items.append({"material_id": src["material_id"], "sku": src["sku"], "name": src.get("name"), "qty": qty, "price": src["price"],
                      "amount": round(qty * src["price"]), "unit_cost": unit_cost, "cogs": round(unit_cost * qty, 2),
                      "condition": ri.get("condition") or "good"})
    factor = (note["subtotal"] - note.get("discount_amount", 0)) / note["subtotal"] if note.get("subtotal") else 1
    subtotal = round(sum(i["amount"] for i in items) * factor)
    tax = round(subtotal * float(note.get("tax_pct") or 0) / 100)
    total = subtotal + tax
    ret_date = body.get("return_date") or date.today().isoformat()
    refund_account = body.get("cash_account_id") if body.get("refund_method") == "cash" else None
    if body.get("refund_method") == "cash" and not refund_account:
        raise HTTPException(400, "Rekening kas wajib untuk refund tunai.")

    ret_doc = {"id": _uid(), "return_number": await gen_prefixed_number(db, RET, "return_number", f"RT-{ret_date.replace('-', '')}-", 3),
               "direct_sale_id": sid, "note_number": note["note_number"], "ar_invoice_id": note.get("ar_invoice_id"), "invoice_number": note.get("invoice_number"),
               "customer_id": note["customer_id"], "customer_name": note.get("customer_name"), "return_date": ret_date,
               "items": items, "subtotal": subtotal, "tax_pct": note.get("tax_pct") or 0, "tax_amount": tax, "total": total,
               "cogs_total": round(sum(i["cogs"] for i in items), 2), "reason": body.get("reason") or "", "status": "posted",
               "created_at": _now(), "updated_at": _now(), "created_by": user["id"], "created_by_name": user.get("name", "")}

    # 1) stok FG kembali + lapisan HPP baru (biaya = HPP saat keluar)
    from core import fg_cost_layers as fcl
    from core import stock_service
    from core.production_qty_ledger import resolve_fg_location_id
    loc = await resolve_fg_location_id(db)
    if not loc:
        raise HTTPException(400, "Lokasi gudang FG (ZNA-FG) tidak ditemukan.")
    ref = {"type": "sales_return", "id": ret_doc["id"], "return_number": ret_doc["return_number"], "note_number": note["note_number"]}
    for it in items:
        if it["condition"] == "damaged":
            continue  # barang rusak tidak kembali ke stok jual
        await stock_service.add(it["material_id"], loc, it["qty"], meta={"inventory_category": "fg_internal", "ownership": "cv_da"}, ref=ref, actor=user, db=db)
        layer = await fcl.push_layer(db, material_id=it["material_id"], qty=it["qty"], po_item={"sku": it["sku"]}, ref=ref, actor=user,
                                     unit_cost=it["unit_cost"], breakdown={"source": "sales_return", "unit_cost": it["unit_cost"]})
        it["layer_id"] = (layer or {}).get("id")

    # 2) nota kredit: Dr Retur Penjualan (+ Dr PPN keluaran) / Cr Piutang pelanggan
    from routes.rahaza_posting import _ar_account_for_invoice, _create_posted_je
    from routes.rahaza_posting_profiles import get_mapping
    cn = {"id": _uid(), "cn_number": await gen_prefixed_number(db, "rahaza_credit_notes", "cn_number", f"CN-{ret_date.replace('-', '')}-", 3),
          "return_id": ret_doc["id"], "direct_sale_id": sid, "ar_invoice_id": note.get("ar_invoice_id"), "customer_id": note["customer_id"],
          "customer_name": note.get("customer_name"), "platform": "direct", "sales_channel": "direct", "issue_date": ret_date,
          "items": [{"description": f"Retur {i['sku']} {i['name'] or ''}".strip(), "qty": i["qty"], "unit": "pcs", "price": i["price"], "amount": i["amount"]} for i in items],
          "subtotal": subtotal, "tax_pct": note.get("tax_pct") or 0, "tax_amount": tax, "total": total, "status": "issued",
          "notes": f"Retur {ret_doc['return_number']} atas nota {note['note_number']}: {ret_doc['reason']}", "created_at": _now(), "updated_at": _now(),
          "created_by": user.get("email", "")}
    await db.rahaza_credit_notes.insert_one(cn)
    cn.pop("_id", None)
    inv = await db.rahaza_ar_invoices.find_one({"id": note.get("ar_invoice_id")}, {"_id": 0}) or {}
    m_cn, m_ar = await get_mapping(db, "credit_note"), await get_mapping(db, "ar_invoice")
    ar_code = await _ar_account_for_invoice(db, inv, m_cn.get("credit_ar") or m_ar.get("debit_ar"))
    rev_code, tax_code = m_cn.get("debit_revenue") or m_ar.get("credit_revenue"), m_ar.get("credit_tax_output")
    cn_post = {"ok": False, "error": "Mapping credit_note/ar_invoice belum lengkap."}
    if ar_code and rev_code and total > 0:
        lines = [{"account_code": rev_code, "debit": subtotal, "credit": 0, "description": f"CN {cn['cn_number']} retur {note['note_number']}"}]
        if tax > 0 and tax_code:
            lines.append({"account_code": tax_code, "debit": tax, "credit": 0, "description": f"CN {cn['cn_number']} PPN keluaran dibalik"})
        elif tax > 0:
            lines[0]["debit"] = total
        lines.append({"account_code": ar_code, "debit": 0, "credit": total, "description": f"CN {cn['cn_number']} piutang {note.get('customer_name')}"})
        cn_post = await _create_posted_je(db, date.fromisoformat(ret_date), f"Credit Note {cn['cn_number']} - retur {note['note_number']}", "credit_note", f"cn:{cn['id']}", lines, user)
        await db.rahaza_credit_notes.update_one({"id": cn["id"]}, {"$set": {"gl_je_id": cn_post.get("je_id"), "gl_je_number": cn_post.get("je_number"), "gl_posted_at": _now(), "post_error": cn_post.get("error")}})

    # 3) terapkan ke invoice: kurangi sisa tagihan; kelebihan = kredit pelanggan (refund tunai bila diminta)
    applied, refund_amount, refund_je, refund_mv = 0.0, 0.0, None, None
    if inv:
        applied = min(total, float(inv.get("balance") or 0))
        excess = round(total - applied)
        new_bal = round(float(inv.get("balance") or 0) - applied)
        upd = {"balance": new_bal, "amount_due": new_bal, "credited_amount": round(float(inv.get("credited_amount") or 0) + total), "updated_at": _now()}
        if new_bal <= 0 and inv.get("status") not in ("paid", "cancelled"):
            upd["status"] = "paid"
        await db.rahaza_ar_invoices.update_one({"id": inv["id"]}, {"$set": upd})
        if excess > 0:
            if refund_account:
                acc = await db.rahaza_cash_accounts.find_one({"id": refund_account}, {"_id": 0})
                if not acc:
                    raise HTTPException(404, "Rekening kas refund tidak ditemukan.")
                refund_mv = _uid()
                await db.rahaza_cash_movements.insert_one({"id": refund_mv, "account_id": refund_account, "account_name": acc.get("name"), "direction": "out",
                                                           "amount": excess, "category": "sales_refund", "ref_id": inv["id"], "ref_label": cn["cn_number"], "date": ret_date,
                                                           "notes": f"Refund retur {ret_doc['return_number']}", "timestamp": _now(), "created_by": user["id"], "created_by_name": user.get("name", "")})
                cash_code = acc.get("gl_account_code") or (await get_mapping(db, "ar_payment")).get("debit_cash")
                if cash_code and ar_code:
                    refund_je = await _create_posted_je(db, date.fromisoformat(ret_date), f"Refund retur {ret_doc['return_number']} ke {note.get('customer_name')}", "sales_refund",
                                                        f"refund:{ret_doc['id']}", [{"account_code": ar_code, "debit": excess, "credit": 0, "description": f"Refund {cn['cn_number']}"},
                                                                                     {"account_code": cash_code, "debit": 0, "credit": excess, "description": f"Refund {cn['cn_number']}"}], user)
                refund_amount = excess
            else:
                ret_doc["customer_credit"] = excess  # saldo kredit pelanggan (belum dikembalikan)

    # 4) balik HPP: Dr 1-1404 / Cr akun COGS asal (proporsional)
    cogs_post = None
    if ret_doc["cogs_total"] > 0:
        m_cogs = await get_mapping(db, "cogs_shipment")
        orig = await db.rahaza_journal_entries.find_one({"id": note.get("cogs_je_id")}, {"_id": 0, "lines": 1}) if note.get("cogs_je_id") else None
        ratio = _ratio_lines(orig) or {m_cogs.get("debit_cogs_material"): 1.0}
        lines = [{"account_code": m_cogs.get("credit_fg_inventory") or "1-1404", "debit": ret_doc["cogs_total"], "credit": 0, "description": f"Retur {ret_doc['return_number']} FG kembali"}]
        acc_amt = 0.0
        codes = list(ratio.items())
        for i, (code, r) in enumerate(codes):
            amt = round(ret_doc["cogs_total"] - acc_amt, 2) if i == len(codes) - 1 else round(ret_doc["cogs_total"] * r, 2)
            acc_amt += amt
            if amt > 0:
                lines.append({"account_code": code, "debit": 0, "credit": amt, "description": f"Retur {ret_doc['return_number']} balik HPP"})
        cogs_post = await _create_posted_je(db, date.fromisoformat(ret_date), f"Balik HPP retur {ret_doc['return_number']} ({note['note_number']})", "cogs_sales_return",
                                            f"cogs_return:{ret_doc['id']}", lines, user)

    ret_doc.update({"cn_id": cn["id"], "cn_number": cn["cn_number"], "cn_je_id": cn_post.get("je_id"), "cn_je_number": cn_post.get("je_number"), "cn_post_error": cn_post.get("error"),
                    "applied_to_invoice": round(applied), "refund_amount": refund_amount, "refund_cash_account_id": refund_account if refund_amount else None,
                    "refund_movement_id": refund_mv, "refund_je_id": (refund_je or {}).get("je_id"),
                    "cogs_je_id": (cogs_post or {}).get("je_id"), "cogs_je_number": (cogs_post or {}).get("je_number"), "cogs_post_error": (cogs_post or {}).get("error")})
    await db[RET].insert_one(ret_doc)
    ret_doc.pop("_id", None)
    await db[COLL].update_one({"id": sid}, {"$inc": {"returned_total": total, "returned_qty": sum(i["qty"] for i in items)}, "$set": {"updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "return", "sales.direct", ret_doc["return_number"])
    return serialize_doc(ret_doc)


@router.get("/returns")
async def list_returns(request: Request, direct_sale_id: Optional[str] = None, limit: int = 300):
    await require_auth(request)
    db = get_db()
    q = {"direct_sale_id": direct_sale_id} if direct_sale_id else {}
    return serialize_doc(await db[RET].find(q, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 1000)))


# ── LAPORAN PENJUALAN ─────────────────────────────────────────────────────────
@router.get("/report")
async def sales_report(request: Request, group_by: str = "customer", date_from: Optional[str] = None, date_to: Optional[str] = None, format: Optional[str] = None):
    await require_auth(request)
    if group_by not in ("customer", "sku", "day", "month"):
        raise HTTPException(400, "group_by harus customer|sku|day|month.")
    db = get_db()
    q = {"status": {"$in": ["confirmed", "paid"]}}
    if date_from or date_to:
        q["sale_date"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    notes = await db[COLL].find(q, {"_id": 0}).to_list(20000)
    rq = {"status": {"$ne": "cancelled"}}
    if date_from or date_to:
        rq["return_date"] = {k: v for k, v in (("$gte", date_from), ("$lte", date_to)) if v}
    rets = await db[RET].find(rq, {"_id": 0}).to_list(20000)
    factor = {n["id"]: ((n["subtotal"] - n.get("discount_amount", 0)) / n["subtotal"] if n.get("subtotal") else 1) for n in notes}
    agg = {}

    def bucket(key, label):
        return agg.setdefault(key, {"key": key, "label": label, "notes": 0, "qty": 0, "gross": 0.0, "discount": 0.0, "tax": 0.0, "net_sales": 0.0,
                                    "cogs": 0.0, "returns": 0.0, "return_qty": 0, "margin": 0.0, "note_ids": set()})

    def key_of(n, it=None):
        if group_by == "customer":
            return n["customer_id"], f"{n.get('customer_code') or ''} {n.get('customer_name') or ''}".strip()
        if group_by == "sku":
            return it["material_id"], f"{it['sku']} · {it.get('name') or ''}"
        d = n["sale_date"] if group_by == "day" else n["sale_date"][:7]
        return d, d

    for n in notes:
        for it in n["items"]:
            k, lbl = key_of(n, it)
            b = bucket(k, lbl)
            b["qty"] += it["qty"]
            b["gross"] += it["amount"]
            b["discount"] += it["amount"] * (1 - factor[n["id"]])
            b["net_sales"] += it["amount"] * factor[n["id"]]
            b["tax"] += it["amount"] * factor[n["id"]] * float(n.get("tax_pct") or 0) / 100
            b["cogs"] += float(it.get("fg_cogs") or 0) + float(it.get("fg_cogs_estimated") or 0)
            b["note_ids"].add(n["id"])
    note_map = {n["id"]: n for n in notes}
    for r in rets:
        n = note_map.get(r["direct_sale_id"]) or {"customer_id": r["customer_id"], "customer_name": r.get("customer_name"), "sale_date": r["return_date"]}
        ret_items_gross = sum(i["amount"] for i in r["items"]) or 1
        for it in r["items"]:
            k, lbl = key_of({**n, "sale_date": r["return_date"] if group_by in ("day", "month") else n.get("sale_date", "")}, it)
            b = bucket(k, lbl)
            b["returns"] += float(r.get("subtotal") or 0) * it["amount"] / ret_items_gross
            b["return_qty"] += it["qty"]
            b["cogs"] -= float(it.get("cogs") or 0)
    rows = []
    for b in agg.values():
        b["notes"] = len(b.pop("note_ids"))
        b["net_sales"] = round(b["net_sales"] - b["returns"], 2)
        b["margin"] = round(b["net_sales"] - b["cogs"], 2)
        b["margin_pct"] = round(b["margin"] / b["net_sales"] * 100, 1) if b["net_sales"] else 0
        for k in ("gross", "discount", "tax", "cogs", "returns"):
            b[k] = round(b[k], 2)
        rows.append(b)
    rows.sort(key=lambda r: (r["key"] if group_by in ("day", "month") else -r["net_sales"]))
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ("qty", "gross", "discount", "tax", "net_sales", "cogs", "returns", "return_qty", "margin")}
    totals["notes"] = len(notes)
    totals["margin_pct"] = round(totals["margin"] / totals["net_sales"] * 100, 1) if totals["net_sales"] else 0
    if format == "csv":
        import csv
        buf = io.StringIO()
        w = csv.writer(buf)
        hdr = {"customer": "Pelanggan", "sku": "SKU", "day": "Tanggal", "month": "Bulan"}[group_by]
        w.writerow([hdr, "Nota", "Qty", "Bruto", "Diskon", "PPN", "Retur", "Penjualan Bersih", "HPP", "Laba Kotor", "Margin %", "Qty Retur"])
        for r in rows:
            w.writerow([r["label"], r["notes"], r["qty"], r["gross"], r["discount"], r["tax"], r["returns"], r["net_sales"], r["cogs"], r["margin"], r["margin_pct"], r["return_qty"]])
        w.writerow(["TOTAL", totals["notes"], totals["qty"], totals["gross"], totals["discount"], totals["tax"], totals["returns"], totals["net_sales"], totals["cogs"], totals["margin"], totals["margin_pct"], totals["return_qty"]])
        return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="laporan_penjualan_{group_by}_{date_from or "awal"}_{date_to or "kini"}.csv"'})
    return {"group_by": group_by, "date_from": date_from, "date_to": date_to, "rows": rows, "totals": totals}
