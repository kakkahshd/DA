#!/usr/bin/env python3
"""verify_coa_unified.py — GATE **INV-F47** (2026-09-12): BAGAN AKUN TUNGGAL & SINKRON.

Keputusan owner: "jangan ada dua skema; default dibuat ulang dengan penyesuaian DA; auto CoA,
default CoA, auto GL semua harus sinkron".

  K1  Tidak ada akun 3 digit (`X-XXX`) yang AKTIF; semua akun aktif berpola `X-XXXX` (+ sub-ledger `-NNN`)
  K2  Semua akun khas DA (data/coa_unified.DA_UNIFIED_ACCOUNTS) ada & aktif (bank per entitas, toko, maklon)
  K3  Setiap akun punya induk yang ada & aktif (tidak ada yatim)
  K4  Profil posting (auto GL): semua kode akun ada, aktif, dan BUKAN header
  K5  Peta akun channel (Shopee/TikTok/Tokopedia/Maklon): kode 4 digit, ada & aktif
  K6  Parent sub-ledger Auto-CoA (pelanggan/supplier/vendor/karyawan): ada & aktif
  K7  Rekening kas/bank & kategori expense menunjuk akun 4 digit yang ada & aktif
  K8  Saldo normal sesuai tipe (ASET/HPP/BEBAN = DEBIT; LIAB/EKUITAS/PENDAPATAN = KREDIT; kontra ditandai)
  K9  Tidak ada nama akun kembar aktif dalam satu induk (sisa penggabungan skema)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from data.coa_unified import DA_UNIFIED_ACCOUNTS  # noqa: E402

G, R, B, X = "\033[92m", "\033[91m", "\033[1m", "\033[0m"
PASS: list[str] = []
FAIL: list[str] = []
FOUR = re.compile(r"^\d-\d{4}(-[A-Za-z0-9]+)*$")
THREE = re.compile(r"^\d-\d{3}($|-)")
NORMAL = {"ASSET": "DEBIT", "COGS": "DEBIT", "EXPENSE": "DEBIT", "OTHER_EXPENSE": "DEBIT",
          "LIABILITY": "CREDIT", "EQUITY": "CREDIT", "REVENUE": "CREDIT", "OTHER_INCOME": "CREDIT"}


def ok(k, m, d=""):
    PASS.append(k); print(f"  {G}✓{X} {k} {m}" + (f" · {d}" if d else ""))


def bad(k, m, d=""):
    FAIL.append(k); print(f"  {R}✗{X} {k} {m}" + (f" · {d}" if d else ""))


def main() -> int:
    from pymongo import MongoClient
    env = {}
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"')
    db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    print(f"{B}INV-F47 — BAGAN AKUN TUNGGAL 4 DIGIT & SINKRON DENGAN AUTO GL{X}")

    acc = list(db.rahaza_coa_accounts.find({}, {"_id": 0}))
    act = {a["code"]: a for a in acc if a.get("active", True)}
    three = [c for c in act if THREE.match(c)]
    notfour = [c for c in act if not FOUR.match(c)]
    if not three and not notfour:
        ok("K1", "semua akun aktif berpola X-XXXX (satu skema)", f"{len(act)} akun aktif · {len(acc) - len(act)} nonaktif")
    else:
        bad("K1", "masih ada akun aktif di luar skema 4 digit", f"3digit={three[:6]} lain={notfour[:6]}")

    # akun pendapatan per toko (4-111x/4-112x/4-113x) mengikuti MASTER TOKO lewat core/finance_sync — yang tokonya
    # tidak ada di master sengaja NONAKTIF (keputusan owner 2026-09-12), bukan hilang.
    byc = {a["code"]: a for a in acc}
    missing = [c for c, *_ in DA_UNIFIED_ACCOUNTS if c not in act
               and not (c in byc and not byc[c].get("active", True) and "finance_sync" in str(byc[c].get("deactivated_reason", "")))]
    (ok if not missing else bad)("K2", "akun khas DA (bank per entitas · toko · maklon) tersemai & aktif",
                                 f"{len(DA_UNIFIED_ACCOUNTS)} akun" if not missing else f"hilang={missing[:8]}")

    orphan = [c for c, a in act.items() if a.get("parent_code") and a["parent_code"] not in act]
    # induk postable dengan anak kontra/detail (1-2200→1-2201 akum. penyusutan; 5-1000→5-1900) adalah
    # konvensi kanonik yang sah — bukan cacat. Yang dilarang: akun yatim & header yang diposting (K4).
    if not orphan:
        ok("K3", "hierarki utuh: tiap akun punya induk yang ada & aktif")
    else:
        bad("K3", "ada akun yatim (induk tidak ada / nonaktif)", f"{orphan[:8]}")

    refs = {}
    for p in db.rahaza_posting_profiles.find({"active": {"$ne": False}}, {"_id": 0, "event_type": 1, "mapping": 1}):
        for k, v in (p.get("mapping") or {}).items():
            if isinstance(v, str) and re.match(r"^\d-\d+", v):
                refs.setdefault(v, []).append(f"{p.get('event_type')}.{k}")
    bad4 = {c: r for c, r in refs.items() if c not in act or act[c].get("is_group") or THREE.match(c)}
    (ok if not bad4 else bad)("K4", "profil posting (auto GL) menunjuk akun 4 digit aktif & postable",
                              f"{len(refs)} kode dirujuk" if not bad4 else str(list(bad4.items())[:5]))

    ch_bad = []
    for ch in db.rahaza_channel_gl_mapping.find({}, {"_id": 0}):
        for k in ("debit_ar", "credit_revenue"):
            v = ch.get(k)
            if v and (v not in act or THREE.match(v)):
                ch_bad.append(f"{ch.get('channel') or ch.get('store_code')}:{k}={v}")
    (ok if not ch_bad else bad)("K5", "peta akun channel memakai akun 4 digit aktif", "; ".join(ch_bad[:5]))

    auto = db.rahaza_coa_auto_settings.find_one({"id": "default"}, {"_id": 0}) or {}
    a_bad = [f"{et}:{(cfg or {}).get('parent_code')}" for et, cfg in (auto.get("entity_types") or {}).items()
             if (cfg or {}).get("parent_code") and (cfg["parent_code"] not in act or THREE.match(cfg["parent_code"]))]
    (ok if not a_bad else bad)("K6", "parent sub-ledger Auto-CoA valid", "; ".join(a_bad[:5]))

    c_bad = [f"{c.get('code')}={c.get('gl_account_code')}" for c in db.rahaza_cash_accounts.find({}, {"_id": 0})
             if c.get("gl_account_code") and (c["gl_account_code"] not in act or THREE.match(c["gl_account_code"]))]
    if "rahaza_expense_categories" in db.list_collection_names():
        for ec in db.rahaza_expense_categories.find({}, {"_id": 0}):
            for k, v in ec.items():
                if isinstance(v, str) and re.match(r"^\d-\d{3,4}$", v) and (v not in act or THREE.match(v)):
                    c_bad.append(f"expcat {ec.get('code') or ec.get('name')}:{k}={v}")
    (ok if not c_bad else bad)("K7", "rekening kas/bank & kategori expense menunjuk akun 4 digit aktif", "; ".join(c_bad[:5]))

    nb_bad = [f"{c}:{a.get('type')}/{a.get('normal_balance')}" for c, a in act.items()
              if not (a.get("flags") or {}).get("is_contra") and NORMAL.get(a.get("type"))
              and a.get("normal_balance") != NORMAL[a["type"]]]
    (ok if not nb_bad else bad)("K8", "saldo normal sesuai tipe (kontra ditandai is_contra)", "; ".join(nb_bad[:6]))

    seen, dup = {}, []
    for c, a in act.items():
        key = (a.get("parent_code"), (a.get("name") or "").strip().lower())
        if key in seen:
            dup.append(f"{seen[key]}~{c}")
        seen[key] = c
    (ok if not dup else bad)("K9", "tidak ada nama akun kembar aktif dalam satu induk", "; ".join(dup[:6]))

    print()
    if FAIL:
        print(f"{R}{B}VERDICT MERAH — {len(FAIL)} invarian gagal: {', '.join(FAIL)}{X}"); return 1
    print(f"{G}{B}VERDICT HIJAU — {len(PASS)} invarian bagan akun tunggal terjaga{X}"); return 0


if __name__ == "__main__":
    sys.exit(main())
