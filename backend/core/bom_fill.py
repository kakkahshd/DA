"""core.bom_fill — importir sheet BOM_AKSESORIS versi 2 (format yang dipakai owner, 2026-09-16).

Aturan berkas:
- Baris dengan `kode_model` = awal KELOMPOK; baris di bawahnya yang `kode_model`-nya kosong = bahan tambahan kelompok yang sama.
- Kolom `varian` (opsional) = daftar warna/ukuran dipisah koma yang memakai bahan kelompok ini. Kosong = semua varian model.
  Bila satu model punya beberapa kelompok tanpa `varian`, warna ditebak dari nama material (mis. "Kancing … warna Hitam");
  kalau tidak bisa ditebak, kelompok DILEWATI dan dilaporkan (bukan diterapkan ke semua varian).
- `qty_per_pcs` boleh berisi satuan: "60 cm", "1 pcs", "0,5 m". Kosong → satuan dasar material.
- Konversi ke satuan dasar: tabel global (cm→m, pcs→gross) + isi kemasan master (pcs→roll/pack lewat pack_size).
- Kode yang mengandung karakter tak terlihat (zero-width space, NBSP) dibersihkan.
"""
from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime, timezone

from core import bom_uom

_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_ZW[0xA0] = 0x20
_QTY_RE = re.compile(r"^\s*([\d.,]+)\s*([a-zA-Z]*)\s*$")
_SPLIT_RE = re.compile(r"[,;/|\n]+")
_COUNT_UNITS = {"pcs", "pc", "piece", "buah", "unit", "lembar", "helai"}


def _now():
    return datetime.now(timezone.utc)


def clean(v) -> str:
    if v in (None, ""):
        return ""
    return str(v).translate(_ZW).strip()


def _num(v) -> float:
    s = clean(v).replace(" ", "")
    if s.count(".") > 1 or (s.count(".") == 1 and "," in s):
        s = s.replace(".", "")
    return float(s.replace(",", ".") or 0)


def parse_qty(v, default_unit: str) -> tuple[float, str]:
    """"60 cm" → (60.0, "cm"); 3 → (3.0, default_unit)."""
    if isinstance(v, (int, float)):
        return float(v), default_unit
    m = _QTY_RE.match(clean(v))
    if not m:
        raise ValueError(f"qty '{clean(v)}' tidak dikenali (contoh: 60 cm, 1 pcs, 0,5)")
    return _num(m.group(1)), (m.group(2).lower() or default_unit)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", clean(s).lower())


def unit_factor(mat: dict, unit: str) -> tuple[float, str, str, str]:
    """(factor→dasar, satuan_dasar, status, catatan). Tambahan: pcs → kemasan lewat pack_size master."""
    f, base, st, note = bom_uom.line_factor(mat, unit)
    if st != "mismatch":
        return f, base, st, note
    pack = float(mat.get("pack_size") or 0)
    if bom_uom.norm_unit(unit) in _COUNT_UNITS and bom_uom.norm_unit(base) in bom_uom.PACKAGING_UNITS and pack > 1:
        return 1.0 / pack, base, "pack", f"1 {base} = {pack:g} pcs (isi kemasan master)"
    return f, base, "mismatch", note


def pcs_uom_row(mat: dict) -> dict | None:
    """Baris UOM 'pcs' yang perlu ditambahkan ke master agar konversi pcs→kemasan resmi tersimpan."""
    pack = float(mat.get("pack_size") or 0)
    base = bom_uom.norm_unit(mat.get("base_uom") or mat.get("unit"))
    if base in bom_uom.PACKAGING_UNITS and pack > 1 and not any(bom_uom.norm_unit(u.get("code")) in _COUNT_UNITS for u in mat.get("uoms") or []):
        return {"code": "pcs", "name": "PCS", "factor": round(1.0 / pack, 8), "is_base": False, "level": 1, "parent": base, "notes": f"1 {base} = {pack:g} pcs"}
    return None


def match_tokens(tokens: list[str], variants: list[dict]) -> tuple[set, set, list]:
    """Cocokkan token varian dengan warna/ukuran varian model (kode, nama, fuzzy ≥ 0.8). → (color_codes, size_codes, unmatched)."""
    color_by_norm: dict[str, str] = {}
    size_by_norm: dict[str, str] = {}
    for v in variants:
        cc = (v.get("color_code") or "").upper()
        if cc:
            color_by_norm[_norm(cc)] = cc
            color_by_norm[_norm(v.get("color_name") or "")] = cc
        sc = (v.get("size_code") or "").upper()
        if sc:
            size_by_norm[_norm(sc)] = sc
    color_by_norm.pop("", None)
    size_by_norm.pop("", None)
    colors, sizes, unmatched = set(), set(), []
    for tok in tokens:
        n = _norm(tok)
        if not n:
            continue
        if n in size_by_norm:
            sizes.add(size_by_norm[n])
        elif n in color_by_norm:
            colors.add(color_by_norm[n])
        else:
            close = difflib.get_close_matches(n, list(color_by_norm), n=1, cutoff=0.8)
            if close:
                colors.add(color_by_norm[close[0]])
            else:
                unmatched.append(tok.strip())
    return colors, sizes, unmatched


def infer_color_from_names(names: list[str], variants: list[dict]) -> set:
    """Warna model yang disebut di nama material (mis. 'Kancing … warna Hitam')."""
    found = set()
    for v in variants:
        cn = _norm(v.get("color_name") or "")
        if len(cn) < 3:
            continue
        for nm in names:
            words = [_norm(w) for w in re.split(r"[\s,/()-]+", nm)]
            if cn in _norm(nm) or any(difflib.SequenceMatcher(None, cn, w).ratio() >= 0.85 for w in words if len(w) >= 3):
                found.add((v.get("color_code") or "").upper())
    return found


def _variants_label(variants: list[dict]) -> str:
    colors = sorted({(v.get("color_name") or v.get("color_code") or "") for v in variants})
    sizes = sorted({v.get("size_code") or "" for v in variants})
    return f"Warna: {', '.join(c for c in colors if c)} · Ukuran: {', '.join(s for s in sizes if s)}"


async def load_model_variants(db, model_ids: list[str]) -> dict:
    out: dict = {}
    async for v in db.rahaza_model_variants.find({"model_id": {"$in": model_ids}, "active": True},
                                                 {"_id": 0, "id": 1, "model_id": 1, "sku": 1, "color_code": 1, "color_name": 1, "size_id": 1, "size_code": 1}):
        out.setdefault(v["model_id"], []).append(v)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# PARSE
# ═══════════════════════════════════════════════════════════════════════════
async def parse_bom_sheet(db, ws, models: dict) -> dict:
    """models = {kode_model: {id, code, name}}. → {bom_groups, bom_lines, bom_warnings}."""
    mat_master = {m["code"]: m for m in await db.rahaza_materials.find({"type": {"$ne": "fg"}, "active": {"$ne": False}}, {"_id": 0}).to_list(30000)}
    rows = list(ws.iter_rows(values_only=True, min_row=2))
    groups: list[dict] = []
    warnings: list[str] = []
    cur: dict | None = None
    for i, r in enumerate(rows, start=2):
        r = tuple(r) + (None,) * (8 - len(r))
        mcode, matcode = clean(r[0]).upper(), clean(r[2]).upper()
        if not mcode and not matcode:
            continue
        if mcode:
            if mcode not in models:
                warnings.append(f"BOM_AKSESORIS baris {i}: model {mcode} tidak ada — kelompok dilewati")
                cur = None
                continue
            cur = {"row": i, "model_code": mcode, "model_id": models[mcode]["id"], "model_name": models[mcode].get("name"),
                   "varian_raw": clean(r[7]), "lines": [], "targets": None, "target_label": "", "note": ""}
            groups.append(cur)
        if cur is None:
            warnings.append(f"BOM_AKSESORIS baris {i}: tidak ada kode_model di atasnya — baris dilewati")
            continue
        if not matcode:
            continue  # baris placeholder template
        mat = mat_master.get(matcode)
        if not mat:
            warnings.append(f"BOM_AKSESORIS baris {i}: material {matcode} tidak ada di master (lihat REF_AKSESORIS) — baris dilewati")
            continue
        base = bom_uom.norm_unit(mat.get("base_uom") or mat.get("unit") or "pcs")
        try:
            qty, unit = parse_qty(r[4], clean(r[5]).lower() or base)
        except ValueError as e:
            warnings.append(f"BOM_AKSESORIS baris {i}: {matcode} — {e} — baris dilewati")
            continue
        if qty <= 0:
            warnings.append(f"BOM_AKSESORIS baris {i}: {mcode}/{matcode} qty_per_pcs wajib > 0 — baris dilewati")
            continue
        f, base, st, note = unit_factor(mat, unit)
        if st == "mismatch":
            warnings.append(f"BOM_AKSESORIS baris {i}: {matcode} satuan '{unit}' tidak bisa dikonversi ke '{base}' "
                            f"(isi 'isi per kemasan' material di master atau tulis qty dalam {base}) — baris dilewati")
            continue
        cur["lines"].append({"row": i, "code": mat["code"], "material_id": mat["id"], "name": mat["name"], "material_type": mat.get("type"),
                             "qty": qty, "unit": bom_uom.norm_unit(unit), "qty_base": round(qty * f, 6), "unit_base": base,
                             "uom_note": note, "add_pcs_uom": st == "pack"})
    groups = [g for g in groups if g["lines"]]
    variants_by_model = await load_model_variants(db, list({g["model_id"] for g in groups}))
    by_model: dict = {}
    for g in groups:
        by_model.setdefault(g["model_id"], []).append(g)
    kept: list[dict] = []
    for model_id, gs in by_model.items():
        variants = variants_by_model.get(model_id) or []
        no_varian = [g for g in gs if not g["varian_raw"]]
        for g in gs:
            if not variants:
                warnings.append(f"BOM_AKSESORIS baris {g['row']}: model {g['model_code']} belum punya varian/SKU (buat dulu di RnD → Master Produk → Varian) — kelompok dilewati")
                continue
            if g["varian_raw"]:
                tokens = [t for t in _SPLIT_RE.split(g["varian_raw"]) if t.strip()]
                colors, sizes, unmatched = match_tokens(tokens, variants)
                if unmatched:
                    warnings.append(f"BOM_AKSESORIS baris {g['row']}: {g['model_code']} varian {unmatched} tidak dikenal ({_variants_label(variants)})"
                                    + (" — token lain tetap dipakai" if (colors or sizes) else " — kelompok dilewati"))
                if not colors and not sizes:
                    continue
                g["targets"] = {"colors": sorted(colors), "sizes": sorted(sizes)}
            elif len(no_varian) > 1:
                inferred = infer_color_from_names([ln["name"] for ln in g["lines"]], variants)
                if len(inferred) == 1:
                    g["targets"] = {"colors": sorted(inferred), "sizes": []}
                    g["note"] = "warna ditebak dari nama material"
                else:
                    mats_txt = "; ".join(ln["name"][:40] for ln in g["lines"][:4])
                    warnings.append(f"BOM_AKSESORIS baris {g['row']}: {g['model_code']} punya {len(no_varian)} kelompok tanpa kolom varian dan warna kelompok ini "
                                    f"({mats_txt}) tidak bisa ditebak dari nama material — isi kolom varian ({_variants_label(variants)}) — kelompok dilewati")
                    continue
            tv = target_variants(g, variants)
            if not tv:
                warnings.append(f"BOM_AKSESORIS baris {g['row']}: {g['model_code']} varian {g['varian_raw']!r} tidak menghasilkan SKU — kelompok dilewati")
                continue
            g["target_skus"] = [v["sku"] for v in tv]
            g["target_label"] = "semua varian" if g["targets"] is None else \
                " · ".join(x for x in (", ".join(g["targets"]["colors"]), ", ".join(g["targets"]["sizes"])) if x)
            kept.append(g)
    flat = [{"row": ln["row"], "model_code": g["model_code"], "model_name": g["model_name"], "target": g["target_label"], "target_skus": len(g["target_skus"]),
             "code": ln["code"], "name": ln["name"], "qty": ln["qty"], "unit": ln["unit"], "qty_base": ln["qty_base"], "unit_base": ln["unit_base"],
             "note": " · ".join(x for x in (g["note"], ln["uom_note"]) if x)} for g in kept for ln in g["lines"]]
    return {"bom_groups": kept, "bom_lines": flat, "bom_warnings": warnings}


def target_variants(g: dict, variants: list[dict]) -> list[dict]:
    t = g.get("targets")
    if not t:
        return list(variants)
    out = []
    for v in variants:
        ok_c = not t["colors"] or (v.get("color_code") or "").upper() in t["colors"]
        ok_s = not t["sizes"] or (v.get("size_code") or "").upper() in t["sizes"]
        if ok_c and ok_s:
            out.append(v)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# APPLY
# ═══════════════════════════════════════════════════════════════════════════
async def apply_bom_groups(db, groups: list[dict], user: dict | None) -> dict:
    from routes.rahaza_bom import resolve_bom_materials
    from core.master_fill import bom_copy_to_missing
    by_model: dict = {}
    for g in groups:
        by_model.setdefault(g["model_id"], []).append(g)
    touched, appended, updated, created, problems, uoms_added = set(), 0, 0, 0, [], 0
    for model_id, gs in by_model.items():
        for ln in (ln for g in gs for ln in g["lines"] if ln.get("add_pcs_uom")):
            mat = await db.rahaza_materials.find_one({"id": ln["material_id"]}, {"_id": 0})
            row = pcs_uom_row(mat) if mat else None
            if row:
                from core.uom import resolve_uoms
                await db.rahaza_materials.update_one({"id": mat["id"]}, {"$set": {"uoms": resolve_uoms(mat) + [row], "updated_at": _now()}})
                uoms_added += 1
        variants = (await load_model_variants(db, [model_id])).get(model_id) or []
        boms = await db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}, "is_active": True}, {"_id": 0}).to_list(2000)
        targets_all = {v["sku"]: v for g in gs for v in target_variants(g, variants)}
        keys = {(b.get("size_id"), (b.get("color_code") or "").upper()) for b in boms}
        missing = [v for v in targets_all.values() if (v.get("size_id"), (v.get("color_code") or "").upper()) not in keys]
        if missing and boms:
            await bom_copy_to_missing(db, user, model_id)
        elif missing:
            for v in missing:
                await db.rahaza_boms.insert_one({"id": str(uuid.uuid4()), "model_id": model_id, "size_id": v.get("size_id"), "color": v.get("color_name"),
                                                 "color_code": (v.get("color_code") or "").upper() or None, "version": 1, "is_active": True, "active": True,
                                                 "materials": [], "notes": "BOM dasar dari sheet BOM_AKSESORIS (kain/potongan belum ada — lengkapi di RnD)",
                                                 "created_by": (user or {}).get("id", "system"), "created_at": _now(), "updated_at": _now()})
                created += 1
        boms = await db.rahaza_boms.find({"model_id": model_id, "active": {"$ne": False}, "is_active": True}, {"_id": 0}).to_list(2000)
        bom_by_key = {(b.get("size_id"), (b.get("color_code") or "").upper()): b for b in boms}
        for g in gs:
            resolved, prob = await resolve_bom_materials(db, [{"material_id": ln["material_id"], "code": ln["code"], "name": ln["name"], "qty": ln["qty"],
                                                              "unit": ln["unit"], "material_type": ln["material_type"], "notes": ""} for ln in g["lines"]],
                                                         strict_accessory=False)
            problems += [f"{g['model_code']}: {p.get('code')} — {p.get('reason')}" for p in prob]
            for v in target_variants(g, variants):
                b = bom_by_key.get((v.get("size_id"), (v.get("color_code") or "").upper()))
                if not b:
                    continue
                mats = list(b.get("materials") or [])
                idx = {(ln.get("material_id") or ln.get("code")): k for k, ln in enumerate(mats)}
                add, upd = [], 0
                for r in resolved:
                    k = idx.get(r.get("material_id") or r.get("code"))
                    if k is None:
                        add.append(dict(r))
                    elif abs(float(mats[k].get("qty") or 0) - float(r["qty"])) > 1e-9 or bom_uom.norm_unit(mats[k].get("unit")) != r["unit"]:
                        mats[k] = {**mats[k], **{kk: r[kk] for kk in ("qty", "unit", "qty_base", "unit_base", "uom_factor", "uom_status", "uom_note", "unit_cost_base") if kk in r}}
                        upd += 1
                if not add and not upd:
                    continue
                mats += add
                await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": mats, "updated_at": _now()},
                                                                  "$push": {"change_log": {"at": _now(), "by": (user or {}).get("name", "system"),
                                                                                           "note": f"BOM_AKSESORIS: +{len(add)} baris, {upd} qty diubah ({g['target_label']})"}}})
                b["materials"] = mats
                touched.add(b["id"])
                appended += len(add)
                updated += upd
    return {"bom_models": len(by_model), "bom_groups": len(groups), "bom_base_created": created, "boms_touched": len(touched),
            "bom_lines_appended": appended, "bom_lines_updated": updated, "bom_pcs_uoms_added": uoms_added, "bom_problems": problems[:20]}
