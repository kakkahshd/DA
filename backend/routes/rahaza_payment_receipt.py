"""Kwitansi PDF per pembayaran AR/AP (Iter 122) — GET /api/rahaza/{ar|ap}-invoices/{iid}/payments/{pid}/receipt.pdf"""
import io
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from auth import require_auth
from database import get_db

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-payment-receipt"])

KIND = {
    "ar": {"payments": "rahaza_ar_payments", "invoices": "rahaza_ar_invoices", "party": "customer_name",
           "title": "KWITANSI PENERIMAAN", "verb": "Telah diterima dari", "party_label": "Diterima dari"},
    "ap": {"payments": "rahaza_ap_payments", "invoices": "rahaza_ap_invoices", "party": "vendor_name",
           "title": "BUKTI PEMBAYARAN", "verb": "Telah dibayarkan kepada", "party_label": "Dibayarkan kepada"},
}

_SATUAN = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]


def terbilang(n: int) -> str:
    n = int(n)
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_SATUAN[n - 10]} belas"
    if n < 100:
        return f"{_SATUAN[n // 10]} puluh {terbilang(n % 10)}".strip()
    if n < 200:
        return f"seratus {terbilang(n - 100)}".strip()
    if n < 1000:
        return f"{_SATUAN[n // 100]} ratus {terbilang(n % 100)}".strip()
    if n < 2000:
        return f"seribu {terbilang(n - 1000)}".strip()
    for div, nama in ((10**12, "triliun"), (10**9, "miliar"), (10**6, "juta"), (1000, "ribu")):
        if n >= div:
            return f"{terbilang(n // div)} {nama} {terbilang(n % div)}".strip()
    return ""


def _rp(n) -> str:
    return "Rp " + f"{round(float(n or 0)):,}".replace(",", ".")


def _fmt_d(s):
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d %B %Y")
    except Exception:  # noqa: BLE001
        return str(s or "-")


def build_receipt_pdf(*, kind: str, pay: dict, inv: dict, account: dict, template: dict, profile: dict, printed_by: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle

    from core.pdf_template import footer_flowables, header_flowables, signature_flowables
    from routes.operations_pdf_helpers import CONTENT_W_PORTRAIT, _build_pdf

    k = KIND[kind]
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=colors.HexColor("#1f2937"))
    muted = ParagraphStyle("muted", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#64748b"))
    big = ParagraphStyle("big", parent=body, fontSize=15, leading=19, textColor=colors.HexColor("#0f172a"))
    avail = CONTENT_W_PORTRAIT
    receipt_no = f"KW-{kind.upper()}-{str(pay.get('date') or '').replace('-', '')}-{str(pay.get('id') or '')[:6].upper()}"
    remaining = float(inv.get("balance") or 0)

    elems = header_flowables(template.get("header"), profile, k["title"], avail=avail,
                             info_pairs=[("No. Kwitansi", receipt_no), ("Tanggal", _fmt_d(pay.get("date"))),
                                         ("No. Invoice", inv.get("invoice_number") or "-"),
                                         ("No. Jurnal", pay.get("gl_je_number") or "-")])
    rows = [
        [Paragraph(f"<b>{k['party_label']}</b>", body), Paragraph(inv.get(k["party"]) or "-", body)],
        [Paragraph("<b>Jumlah</b>", body), Paragraph(f"<b>{_rp(pay.get('amount'))}</b>", big)],
        [Paragraph("<b>Terbilang</b>", body), Paragraph(f"<i>{terbilang(round(float(pay.get('amount') or 0))).capitalize()} rupiah</i>", body)],
        [Paragraph("<b>Untuk pembayaran</b>", body),
         Paragraph(f"Invoice {inv.get('invoice_number') or '-'} · total {_rp(inv.get('total'))} · "
                   f"{'LUNAS' if remaining <= 0 else 'sisa tagihan ' + _rp(remaining)}", body)],
        [Paragraph("<b>Metode / Rekening</b>", body),
         Paragraph(f"{account.get('code')} · {account.get('name')}" + (f" ({account.get('bank_name')})" if account.get('bank_name') else "")
                   if account else "Tanpa rekening (kas)", body)],
    ]
    if pay.get("notes"):
        rows.append([Paragraph("<b>Catatan</b>", body), Paragraph(str(pay["notes"]), body)])
    t = Table(rows, colWidths=[avail * 0.28, avail * 0.72])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
                           ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f5f9"))]))
    elems += [Spacer(1, 3 * mm), t, Spacer(1, 4 * mm)]
    elems.extend(signature_flowables(template.get("signatures"), {
        "customer_name": inv.get(k["party"]) or "", "invoice_number": inv.get("invoice_number") or "",
        "confirmed_by": pay.get("created_by_name") or "", "printed_by": printed_by}, avail=avail))
    elems += [Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#cbd5e1")),
              Paragraph(f"Dicetak oleh {printed_by or '-'} · kwitansi ini sah tanpa tanda tangan basah bila disertai nomor jurnal.", muted)]
    elems.extend(footer_flowables(template.get("footer"), profile))
    return _build_pdf(io.BytesIO(), elems, page=template.get("page")).getvalue()


@router.get("/{kind}-invoices/{iid}/payments/{pid}/receipt.pdf")
async def payment_receipt_pdf(kind: str, iid: str, pid: str, request: Request):
    user = await require_auth(request)
    if kind not in KIND:
        raise HTTPException(404, "Jenis invoice tidak dikenal.")
    db = get_db()
    k = KIND[kind]
    pay = await db[k["payments"]].find_one({"id": pid, "invoice_id": iid}, {"_id": 0})
    if not pay:
        raise HTTPException(404, "Pembayaran tidak ditemukan.")
    inv = await db[k["invoices"]].find_one({"id": iid}, {"_id": 0}) or {}
    if not inv.get(k["party"]):
        coll, fk = ("rahaza_customers", "customer_id") if kind == "ar" else ("rahaza_vendors", "vendor_id")
        party = await db[coll].find_one({"id": inv.get(fk)}, {"_id": 0, "name": 1}) if inv.get(fk) else None
        inv[k["party"]] = (party or {}).get("name") or inv.get("customer") or inv.get("vendor") or "-"
    account = await db.rahaza_cash_accounts.find_one({"id": pay.get("account_id")}, {"_id": 0}) if pay.get("account_id") else None
    from core import pdf_template
    template = await pdf_template.resolve(db, "sales-note")
    profile = await pdf_template.company_profile(db)
    pdf = build_receipt_pdf(kind=kind, pay=pay, inv=inv, account=account, template=template, profile=profile,
                            printed_by=user.get("name") or "")
    fname = f"Kwitansi_{inv.get('invoice_number', iid)}_{str(pid)[:6]}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})
