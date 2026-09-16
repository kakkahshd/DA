#!/usr/bin/env python3
"""cleanup_uji_iter120_finance.py — sapu artefak uji iter 119/120 (AR diskon, pembayaran ganda,
void jurnal, kasbon payroll). Data uji dibuat lewat API sungguhan pada 2026-09-05/06 untuk
karyawan demo `int-demo-op-1` dan pelanggan uji `TESTITER*`.

YANG DISAPU: AR invoice uji (+ pembayaran, mutasi kas, JE & cermin baris jurnal), pelanggan
uji, kasbon `int-demo-op-1` (+ JE), payroll run PR-20260905-* (+ payslip + JE), JE manual uji.
TIDAK DISENTUH: counters (nomor dokumen dibiarkan maju).

Pakai:  python3 scripts/cleanup_uji_iter120_finance.py          # laporan
        python3 scripts/cleanup_uji_iter120_finance.py --apply  # hapus
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from gr_common import db_handle  # noqa: E402

DEMO_EMP = "int-demo-op-1"
AR_RX = "^AR-2026090[56]-"
RUN_RX = "^PR-2026090[56]-"


def main() -> int:
    apply = "--apply" in sys.argv
    db = db_handle()

    ar = list(db.rahaza_ar_invoices.find({"invoice_number": {"$regex": AR_RX}}, {"_id": 0, "id": 1, "invoice_number": 1}))
    ar_ids = [a["id"] for a in ar]
    cust_ids = [c["id"] for c in db.rahaza_customers.find({"name": {"$regex": "^TESTITER"}}, {"_id": 0, "id": 1})]
    ar_pay = list(db.rahaza_ar_payments.find({"invoice_id": {"$in": ar_ids}}, {"_id": 0, "id": 1, "movement_id": 1}))
    ap = list(db.rahaza_ap_invoices.find({"created_at": {"$gte": "2026-09-05"}, "vendor_name": {"$regex": "TEST|UJI|Uji", "$options": "i"}}, {"_id": 0, "id": 1}))
    ap_ids = [a["id"] for a in ap]
    ap_pay = list(db.rahaza_ap_payments.find({"invoice_id": {"$in": ap_ids}}, {"_id": 0, "id": 1, "movement_id": 1}))
    kas = list(db.dewi_kasbon_requests.find({"employee_id": DEMO_EMP}, {"_id": 0, "id": 1, "request_number": 1}))
    kas_ids = [k["id"] for k in kas]
    runs = list(db.rahaza_payroll_runs.find({"run_number": {"$regex": RUN_RX}}, {"_id": 0, "id": 1, "run_number": 1}))
    run_ids = [r["id"] for r in runs]
    mov_ids = [p["movement_id"] for p in ar_pay + ap_pay if p.get("movement_id")]

    ref_ids = ar_ids + ap_ids + kas_ids + run_ids + mov_ids + [p["id"] for p in ar_pay + ap_pay]
    je_q = {"$or": [
        {"source_ref": {"$regex": "|".join(ref_ids)}} if ref_ids else {"id": None},
        {"memo": {"$regex": "uji|TESTITER|Uji", "$options": "i"}, "source_module": {"$in": ["manual", "manual_journal", None]}},
    ]}
    jes = list(db.rahaza_journal_entries.find(je_q, {"_id": 0, "id": 1, "je_number": 1, "source_module": 1}))
    je_ids = [j["id"] for j in jes]

    print(f"AR uji: {len(ar)} {[a['invoice_number'] for a in ar]}")
    print(f"Pelanggan uji: {len(cust_ids)} · pembayaran AR: {len(ar_pay)} · AP uji: {len(ap)} · pembayaran AP: {len(ap_pay)}")
    print(f"Kasbon {DEMO_EMP}: {len(kas)} {[k['request_number'] for k in kas]}")
    print(f"Payroll run: {len(runs)} {[r['run_number'] for r in runs]}")
    print(f"JE terkait: {len(jes)} {[ (j['je_number'], j['source_module']) for j in jes]}")
    if not apply:
        print("\n(laporan saja — tambahkan --apply untuk menghapus)")
        return 0

    db.rahaza_journal_lines.delete_many({"je_id": {"$in": je_ids}})
    db.rahaza_journal_entries.delete_many({"id": {"$in": je_ids}})
    db.rahaza_cash_movements.delete_many({"id": {"$in": mov_ids}})
    db.rahaza_ar_payments.delete_many({"invoice_id": {"$in": ar_ids}})
    db.rahaza_ap_payments.delete_many({"invoice_id": {"$in": ap_ids}})
    db.rahaza_ar_invoices.delete_many({"id": {"$in": ar_ids}})
    db.rahaza_ap_invoices.delete_many({"id": {"$in": ap_ids}})
    db.rahaza_customers.delete_many({"id": {"$in": cust_ids}})
    db.dewi_kasbon_requests.delete_many({"id": {"$in": kas_ids}})
    db.rahaza_payslips.delete_many({"run_id": {"$in": run_ids}})
    db.rahaza_payroll_runs.delete_many({"id": {"$in": run_ids}})
    print("\nDihapus. Sisa: AR", db.rahaza_ar_invoices.count_documents({"invoice_number": {"$regex": AR_RX}}),
          "· kasbon demo", db.dewi_kasbon_requests.count_documents({"employee_id": DEMO_EMP}),
          "· run", db.rahaza_payroll_runs.count_documents({"run_number": {"$regex": RUN_RX}}),
          "· JE", db.rahaza_journal_entries.count_documents({"id": {"$in": je_ids}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
