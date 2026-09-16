#!/usr/bin/env python3
"""verify_finance_sync.py — GATE **INV-F49** (2026-09-12): MASTER KEUANGAN ↔ BAGAN AKUN SINKRON.

  S1  Tiap akun kas/bank/dompet postable di CoA ↔ tepat SATU rekening Kas & Bank (gl_account_code), tanpa akun 1-1200-XXX yatim
  S2  Tiap rekening aktif punya gl_account_code yang ada, aktif, postable, dan berada di bawah Kas/Bank
  S3  Auto Akun cmt_vendor → vendor_partners, induk 2-1110; profil posting cmt_ap_invoice.credit_ap = 2-1110
  S4  Semua vendor CMT aktif punya sub-ledger 2-1110-<kode>; klien maklon → 1-1305-<kode>; toko → 1-1303-<kode>
  S5  Tiap toko aktif punya coa_revenue_code (akun aktif postable di 4-11xx) & baris Peta Akun Channel aktif (kunci = kode toko)
  S6  Semua kode di profil posting & peta channel aktif menunjuk akun aktif non-header
  S7  Tidak ada nama akun kas/bank aktif kembar; tidak ada sub-ledger CMT di bawah 2-1100 untuk vendor_partners
  S8  API: Tambah rekening dgn gl_account_code yang sudah tertaut → 409; gl_account_code asal → 400; sinkron ulang idempoten (0 perubahan)
  S9  Bersih: artefak uji dihapus
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib.gr_common import db_handle, http, login  # noqa: E402

G, R, X = "\033[92m", "\033[91m", "\033[0m"
PASS: list[str] = []
FAIL: list[str] = []


def check(k, cond, m, d=""):
    (PASS if cond else FAIL).append(k)
    print(f"  {G if cond else R}{'✓' if cond else '✗'}{X} {k} {m}" + (f" · {d}" if d else ""))


def main() -> int:
    tok = login()
    if not tok:
        print("backend/login tidak siap"); return 2
    db = db_handle()
    coa = {a["code"]: a for a in db.rahaza_coa_accounts.find({}, {"_id": 0})}
    act = {c: a for c, a in coa.items() if a.get("active", True)}

    def under(code, roots):
        seen = 0
        while code and seen < 8:
            if code in roots:
                return True
            code = (coa.get(code) or {}).get("parent_code"); seen += 1
        return False

    cash_leaves = {c for c, a in act.items() if not a.get("is_group") and under(c, {"1-1100", "1-1200"})}
    regs = list(db.rahaza_cash_accounts.find({"active": {"$ne": False}}, {"_id": 0}))
    gl_of = [r.get("gl_account_code") for r in regs]
    unlinked = sorted(cash_leaves - set(gl_of))
    dup = sorted({g for g in gl_of if g and gl_of.count(g) > 1})
    check("S1", not unlinked and not dup, "tiap akun kas/bank CoA ↔ satu rekening", f"tanpa rekening={unlinked[:5]} dobel={dup[:5]} rekening={len(regs)}")
    bad = [r["code"] for r in regs if not r.get("gl_account_code") or r["gl_account_code"] not in act or act[r["gl_account_code"]].get("is_group") or not under(r["gl_account_code"], {"1-1100", "1-1200"})]
    check("S2", not bad, "tiap rekening punya GL aktif postable di bawah Kas/Bank", f"buruk={bad[:5]}")

    st = db.rahaza_coa_auto_settings.find_one({"id": "default"}, {"_id": 0}) or {}
    cv = (st.get("entity_types") or {}).get("cmt_vendor") or {}
    prof = (db.rahaza_posting_profiles.find_one({"event_type": "cmt_ap_invoice"}, {"_id": 0}) or {}).get("mapping") or {}
    check("S3", cv.get("collection") == "vendor_partners" and cv.get("parent_code") == "2-1110" and prof.get("credit_ap") == "2-1110",
          "auto akun CMT → vendor_partners/2-1110 & profil cmt_ap_invoice.credit_ap 2-1110", f"{cv.get('collection')} {cv.get('parent_code')} {prof.get('credit_ap')}")

    def missing(coll, field, prefix):
        return [e.get("code") or e.get("account_code") for e in db[coll].find({"active": {"$ne": False}}, {"_id": 0})
                if not str(e.get(field) or "").startswith(prefix + "-") or e.get(field) not in act]
    m1, m2, m3 = missing("vendor_partners", "ap_account_code", "2-1110"), missing("dewi_maklon_clients", "ar_account_code", "1-1305"), missing("marketing_platform_accounts", "ar_account_code", "1-1303")
    check("S4", not (m1 or m2 or m3), "sub-ledger vendor CMT / klien maklon / toko lengkap", f"cmt={m1[:3]} maklon={m2[:3]} toko={m3[:3]}")

    stores = list(db.marketing_platform_accounts.find({"active": {"$ne": False}}, {"_id": 0}))
    bad5 = []
    for s in stores:
        rc = s.get("coa_revenue_code")
        cm = db.rahaza_channel_gl_mapping.find_one({"channel_key": s.get("account_code"), "active": True}, {"_id": 0})
        if not rc or rc not in act or act[rc].get("is_group") or not rc.startswith("4-11") or not cm or cm.get("credit_revenue") != rc:
            bad5.append(s.get("account_code"))
    check("S5", not bad5 and stores, "tiap toko punya akun pendapatan 4-11xx + baris Peta Akun Channel", f"toko={len(stores)} buruk={bad5}")

    bad6 = []
    for p in db.rahaza_posting_profiles.find({}, {"_id": 0, "event_type": 1, "mapping": 1}):
        for k, v in (p.get("mapping") or {}).items():
            if v not in act or act[v].get("is_group"):
                bad6.append(f"{p['event_type']}.{k}={v}")
    for cm in db.rahaza_channel_gl_mapping.find({"active": True}, {"_id": 0}):
        for k in ("debit_ar", "credit_revenue"):
            if cm.get(k) not in act or act[cm[k]].get("is_group"):
                bad6.append(f"channel:{cm.get('channel_key')}.{k}={cm.get(k)}")
    check("S6", not bad6, "profil posting & peta channel menunjuk akun aktif non-header", f"{bad6[:5]}")

    names = [a["name"].strip().lower() for c, a in act.items() if c in cash_leaves]
    dupn = sorted({n for n in names if names.count(n) > 1})
    orphan = [c for c, a in act.items() if c.startswith("2-1100-") and (a.get("flags") or {}).get("subledger_entity_type") == "cmt_vendor"]
    check("S7", not dupn and not orphan, "tanpa nama kas/bank kembar & tanpa sub-ledger CMT di 2-1100", f"kembar={dupn[:3]} yatim={orphan[:3]}")

    linked_code = next((g for g in gl_of if g), "")
    st1, t1 = http("POST", "/rahaza/cash-accounts", tok, {"code": "GATE-F49-A", "name": "Uji F49", "type": "bank", "gl_account_code": linked_code})
    st2, t2 = http("POST", "/rahaza/cash-accounts", tok, {"code": "GATE-F49-B", "name": "Uji F49", "type": "bank", "gl_account_code": "9-9999"})
    before = (db.rahaza_coa_accounts.count_documents({}), db.rahaza_cash_accounts.count_documents({}), db.rahaza_channel_gl_mapping.count_documents({}))
    st3, t3 = http("POST", "/rahaza/finance/sync-masters", tok, {})
    rep = json.loads(t3) if st3 == 200 else {}
    after = (db.rahaza_coa_accounts.count_documents({}), db.rahaza_cash_accounts.count_documents({}), db.rahaza_channel_gl_mapping.count_documents({}))
    idem = st3 == 200 and before == after and not rep.get("cash_accounts_created") and not rep["stores"]["revenue_created"] and not any(rep["subledgers_created"].values())
    check("S8", st1 == 409 and st2 == 400 and idem, "API: GL tertaut → 409, GL asal → 400, sinkron ulang idempoten", f"{st1} {st2} {st3} idem={idem}")

    db.rahaza_cash_accounts.delete_many({"code": {"$regex": "^GATE-F49"}})
    db.rahaza_coa_accounts.delete_many({"name": {"$regex": "Uji F49"}})
    check("S9", db.rahaza_cash_accounts.count_documents({"code": {"$regex": "^GATE-F49"}}) == 0, "artefak uji bersih")
    print(f"\n{'HIJAU' if not FAIL else 'MERAH'}: {len(PASS)} lulus · {len(FAIL)} gagal {FAIL}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
