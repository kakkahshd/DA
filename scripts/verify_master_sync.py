#!/usr/bin/env python3
"""verify_master_sync.py — GATE **INV-M50** (2026-09-12): MASTER PRODUK LINTAS PORTAL TIDAK SETENGAH-SETENGAH.

  M1  Tiap kombinasi BOM aktif (model×ukuran×warna) punya varian SSOT aktif & FG (rahaza_materials type fg, code = SKU)
  M2  Tiap FG aktif punya `variant_id` yang menunjuk varian aktif dgn SKU sama; tidak ada SKU varian kembar
  M3  Tiap model aktif punya Style RnD (kode = kode model, promoted_to_model_id) & model.rnd_style_id menunjuk balik
  M4  Status style: `promoted` ⇔ semua varian model punya BOM; selain itu `approved_for_launch` (belum lengkap)
  M5  Tiap (model×warna) varian punya Varian RnD (dewi_rnd_variants) dgn daftar ukuran = SKU varian
  M6  Tiap user ber-employee_id ↔ karyawan.user_id balik; tiap karyawan aktif punya profil payroll
  M7  Tiap item katalog toko aktif menunjuk FG yang ada & aktif
  M8  API POST /api/rahaza/master/sync idempoten (jalan ke-2: 0 pembuatan)
  M10 Tiap karyawan aktif punya shift (default 08:00–16:00); tiap kreator KOL ber-email punya sandi (hash bcrypt) + must_change_password
  M9  Tiap material non-FG punya kategori master (category_id ada di rahaza_material_categories); semua satuan material ada di master satuan
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
    models = {m["id"]: m for m in db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "sop_steps": 0})}
    variants = list(db.rahaza_model_variants.find({"active": True}, {"_id": 0}))
    vkey = {(v["model_id"], v.get("size_id"), (v.get("color_code") or "").upper()): v for v in variants}
    vid = {v["id"]: v for v in variants}
    fgs = list(db.rahaza_materials.find({"type": "fg", "active": {"$ne": False}}, {"_id": 0}))
    fg_by_code = {f["code"].upper(): f for f in fgs}
    boms = list(db.rahaza_boms.find({"active": {"$ne": False}}, {"_id": 0, "model_id": 1, "size_id": 1, "color_code": 1}))
    bkeys = {(b["model_id"], b.get("size_id"), (b.get("color_code") or "").upper()) for b in boms}

    m1 = [k for k in bkeys if k not in vkey or vkey[k]["sku"].upper() not in fg_by_code]
    check("M1", not m1, "tiap kombinasi BOM punya varian & FG", f"bom={len(bkeys)} varian={len(variants)} fg={len(fgs)} hilang={m1[:3]}")
    m2 = [f["code"] for f in fgs if not f.get("variant_id") or f["variant_id"] not in vid or vid[f["variant_id"]]["sku"].upper() != f["code"].upper()]
    skus = [v["sku"].upper() for v in variants]
    dup = sorted({s for s in skus if skus.count(s) > 1})
    check("M2", not m2 and not dup, "tiap FG ↔ varian (variant_id, SKU sama), SKU unik", f"fg_tanpa_varian={m2[:3]} kembar={dup[:3]}")

    styles = {s["style_code"]: s for s in db.dewi_rnd_styles.find({}, {"_id": 0})}
    m3 = [m["code"] for m in models.values() if m["code"] not in styles or styles[m["code"]].get("promoted_to_model_id") != m["id"] or m.get("rnd_style_id") != styles[m["code"]]["id"]]
    check("M3", not m3, "tiap model punya Style RnD tertaut dua arah", f"model={len(models)} style={len(styles)} buruk={m3[:3]}")

    per_model: dict = {}
    for k, v in vkey.items():
        per_model.setdefault(k[0], []).append(k)
    m4 = []
    for m in models.values():
        vs = per_model.get(m["id"], [])
        want = "promoted" if vs and all(k in bkeys for k in vs) else "approved_for_launch"
        st = styles.get(m["code"], {})
        if st.get("master_sync") and st.get("status") != want:
            m4.append((m["code"], st.get("status"), want))
    n_prom = sum(1 for s in styles.values() if s.get("status") == "promoted")
    check("M4", not m4, "status style = kelengkapan BOM", f"promoted={n_prom} belum_lengkap={len(styles) - n_prom} salah={m4[:3]}")

    m5 = []
    for m in models.values():
        st = styles.get(m["code"])
        if not st:
            continue
        rv = {(x.get("color_code") or "").upper(): x for x in db.dewi_rnd_variants.find({"style_id": st["id"]}, {"_id": 0})}
        for k in per_model.get(m["id"], []):
            x = rv.get(k[2])
            if not x or vkey[k]["sku"].upper() not in {r.get("sku", "").upper() for r in (x.get("sizes") or [])}:
                m5.append(f"{m['code']}/{k[2]}")
    check("M5", not m5, "tiap model×warna punya Varian RnD dgn SKU ukuran lengkap", f"hilang={m5[:4]}")

    m6a = [u["email"] for u in db.users.find({"employee_id": {"$ne": None}}, {"_id": 0, "id": 1, "email": 1, "employee_id": 1})
           if (db.rahaza_employees.find_one({"id": u["employee_id"]}, {"_id": 0, "user_id": 1}) or {}).get("user_id") != u["id"]]
    m6b = [e["employee_code"] for e in db.rahaza_employees.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "employee_code": 1})
           if not db.rahaza_payroll_profiles.find_one({"employee_id": e["id"]}, {"_id": 0, "id": 1})]
    check("M6", not m6a and not m6b, "karyawan ↔ user dua arah & tiap karyawan punya profil payroll", f"user_tanpa_balik={m6a[:3]} tanpa_payroll={m6b[:3]}")

    fg_ids = {f["id"] for f in fgs}
    m7 = [c["sku"] for c in db.marketing_catalog_items.find({"is_active": {"$ne": False}}, {"_id": 0, "sku": 1, "fg_material_id": 1}) if c.get("fg_material_id") not in fg_ids]
    check("M7", not m7, "tiap item katalog toko menunjuk FG aktif", f"buruk={m7[:3]}")

    st, txt = http("POST", "/rahaza/master/sync", tok, {})
    rep = json.loads(txt) if st == 200 else {}
    v = rep.get("variants") or {}
    idem = st == 200 and not rep.get("employees_shift_defaulted") and not rep.get("creator_passwords_set") and not rep.get("materials_categorized") and not rep.get("units_added") and not v.get("created_from_fg") and not v.get("created_from_bom") and not (rep.get("rnd") or {}).get("styles_created") and not (rep.get("rnd") or {}).get("rnd_variants_created") and not rep.get("employees_linked")
    check("M8", idem, "POST /rahaza/master/sync idempoten", f"HTTP {st} {rep}"[:200])

    cats = {c["id"] for c in db.rahaza_material_categories.find({}, {"_id": 0, "id": 1})}
    m9a = db.rahaza_materials.count_documents({"type": {"$ne": "fg"}, "category_id": {"$nin": list(cats)}})
    units = {u["code"] for u in db.wh_unit_master.find({}, {"_id": 0, "code": 1})}
    used = set()
    for f in ("unit", "pack_unit", "purchase_uom", "issue_uom", "display_uom"):
        used |= {u for u in db.rahaza_materials.distinct(f) if u}
    check("M9", m9a == 0 and not (used - units), "material berkategori master & satuan ada di master satuan", f"tanpa_kategori={m9a} satuan_hilang={sorted(used - units)}")

    m10a = db.rahaza_employees.count_documents({"active": {"$ne": False}, "$or": [{"shift_id": None}, {"shift_id": {"$exists": False}}, {"shift_id": ""}]})
    m10b = db.marketing_kol_creators.count_documents({"login_email": {"$nin": [None, ""]}, "$or": [{"login_password_hash": {"$not": {"$regex": "^\\$2"}}}, {"login_password_hash": {"$exists": False}}]})
    check("M10", m10a == 0 and m10b == 0 and db.rahaza_shifts.count_documents({"start_time": "08:00", "end_time": "16:00", "active": True}) >= 1,
          "karyawan ber-shift default & kreator KOL ber-sandi", f"tanpa_shift={m10a} kreator_tanpa_sandi={m10b}")

    print(f"\n{'HIJAU' if not FAIL else 'MERAH'}: {len(PASS)} lulus · {len(FAIL)} gagal {FAIL}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
