"""Validasi dan penyimpanan BOM importir; tidak menebak resep atau menimpa BOM manual."""
from collections import Counter, defaultdict
import hashlib
import json
import math

from core import bom_uom
from core import cut_panel_master


async def panelize_lines(db, lines, mk, sk, ck, color, mdl, siz, apply, api, rowno, label):
    """Ganti baris kain roll dengan 1 pcs potongan (SSOT core.cut_panel_master)."""
    fabric = [ln for ln in lines if ln.get('material_type') in ('fabric',) and not cut_panel_master.is_panel_line(ln)]
    if not fabric:
        return lines
    if len(fabric) > 1:
        api.err('10_BOM', rowno, f'{label}: {len(fabric)} baris kain dalam satu resep — potongan hanya '
                                 f'bisa menunjuk satu kain asal; konfirmasi klien kain mana yang dipotong')
        return None
    fl = fabric[0]
    model = await db.rahaza_models.find_one({'id': mdl[mk]}, {'_id': 0, 'id': 1, 'code': 1, 'name': 1}) \
        or {'id': mdl[mk], 'code': mk, 'name': mk}
    src = await db.rahaza_materials.find_one({'id': fl['material_id']}, {'_id': 0, 'id': 1, 'code': 1, 'composition': 1}) \
        or {'id': fl['material_id'], 'code': fl['code']}
    panel, created = await cut_panel_master.ensure_panel(
        db, model=model, color_code=ck, color_name=color, size_code=sk, size_id=siz[sk],
        source_fabric=src, created_from='bom_import', apply=apply)
    st = api.STATS.setdefault('10_BOM·potongan', {'baru': 0, 'diperbarui': 0})
    st['baru' if created else 'diperbarui'] += 1
    if apply and created:
        await db.rahaza_materials.update_one({'id': panel['id']}, {'$set': {'import_batch': api.BATCH}})
    return [cut_panel_master.bom_line_for_panel(panel, fl) if ln is fl else ln for ln in lines]


def fingerprint(doc):
    keys = ('material_id', 'code', 'qty', 'unit', 'qty_base', 'unit_base', 'notes')
    data = {'color': doc.get('color') or '',
            'materials': [{k: m.get(k) for k in keys} for m in doc.get('materials', [])]}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def extreme(qty, unit):
    """Ambang fisik juga berlaku untuk gram/meter; tidak terlewati dengan mengganti unit."""
    for target, limit in [('kg', 5), ('yard', 10)]:
        factor = bom_uom.global_factor(unit, target)
        if factor and qty * factor > limit + 1e-9:
            return f'qty ekstrem {qty * factor:g} {target}/pcs > {limit} {target}/pcs; konfirmasi klien'
    return ''


def convert_line(r, material, api):
    qty = api.num(r.get('qty_per_pcs'))
    if not api.is_num(r.get('qty_per_pcs')) or not math.isfinite(qty) or qty <= 0:
        api.err('10_BOM', r['__row'], 'qty_per_pcs harus angka lebih besar dari 0 (bukan teks/kosong/tak hingga)')
        return None
    unit = api.s(r.get('satuan')) or material.get('base_uom') or material.get('unit')
    raw_problem = extreme(qty, unit)
    factor, base, status, note = bom_uom.line_factor(material, unit)
    cross = {bom_uom.dimension_of(unit), bom_uom.dimension_of(base)} == {'length', 'mass'}
    if cross and not bom_uom.fabric_kg_per_meter(material):
        api.err('10_BOM', r['__row'], f"{material['code']}: {unit}→{base} memerlukan gramasi_gsm dan lebar_cm positif; tidak boleh ditebak")
        return None
    if status in ('mismatch', 'unlinked') or not math.isfinite(factor) or factor <= 0:
        api.err('10_BOM', r['__row'], f"{material['code']}: satuan '{unit}' tidak dapat dikonversi ke '{base}'; lengkapi satuan/GSM/lebar")
        return None
    problem = raw_problem or extreme(qty * factor, base)
    if problem:
        api.err('10_BOM', r['__row'], f"{material['code']}: {problem}")
        return None
    # Qty tersimpan dalam satuan stok, sehingga konsumen lama pun tidak salah 100x.
    # Sumber/faktor tetap utuh untuk audit dan reproduksi perhitungan.
    converted = qty * factor
    if not math.isfinite(converted) or round(converted, 8) <= 0:
        api.err('10_BOM', r['__row'], 'Hasil konversi qty tidak valid/terlalu kecil')
        return None
    if status != 'base':
        api.warn('10_BOM', r['__row'], f"{material['code']}: {qty:g} {unit} → {converted:.8g} {base} ({status}); {note}")
    return {'material_id': material['id'], 'code': material['code'], 'name': material['name'],
            'material_type': material.get('type'), 'category_name': material.get('category_name') or '',
            'qty': round(converted, 8), 'unit': base, 'qty_base': round(converted, 8),
            'unit_base': base, 'uom_factor': 1.0, 'uom_status': 'base', 'uom_note': '',
            'unit_cost_base': material.get('unit_cost') or 0,
            'source_qty': qty, 'source_unit': unit, 'source_uom_factor': factor,
            'source_uom_status': status, 'source_row': r['__row'],
            'notes': api.s(r.get('keterangan'))}


async def import_boms(wb, db, pending, mdl, siz, col, apply, api, pending_colors=None):
    recs = api.check_required('10_BOM', api.read_sheet(wb, '10_BOM'))
    mdocs = {api.s(d.get('code')).upper(): d for d in await db.rahaza_materials.find(
        {}, {'_id': 0}).to_list(50000)}
    mdocs.update(pending)
    color_docs = {api.s(d.get('code')).upper(): d for d in await db.rahaza_colors.find(
        {}, {'_id': 0}).to_list(5000)}
    color_docs.update(pending_colors or {})
    groups, evidence = defaultdict(list), defaultdict(list)
    for r in recs:
        mk, sk, ck, mc = [api.s(r.get(k)).upper() for k in
                         ('kode_model', 'kode_ukuran', 'kode_warna', 'kode_material')]
        key = (mk, sk, ck)
        evidence[key].append((r, mdocs.get(mc)))
        bad = [f"{label} '{code}' belum ada di {sheet}" for label, code, mapping, sheet in
               [('kode_model', mk, mdl, '08_MODEL'), ('kode_ukuran', sk, siz, '04_UKURAN'),
                ('kode_warna', ck, col, '03_WARNA')] if (label != 'kode_warna' or ck) and code not in mapping]
        if bad:
            api.err('10_BOM', r['__row'], '; '.join(bad))
            continue
        material = mdocs.get(mc)
        if material and material.get('type') == 'fg':
            api.err('10_BOM', r['__row'], f"kode_material '{mc}' adalah BARANG JADI — barang jadi tidak boleh menjadi komponen BOM")
            continue
        if not material:
            extra = extreme(api.num(r.get('qty_per_pcs')), r.get('satuan'))
            api.err('10_BOM', r['__row'], f"kode_material '{mc}' tidak ada di master bahan/aksesoris 06/07" + (f'; {extra}' if extra else ''))
            continue
        line = convert_line(r, material, api)
        if line:
            groups[key].append(line)

    for key, rows in evidence.items():
        mk, sk, ck = key
        label = f'{mk}/{sk}/{ck or "UMUM"}'
        rowno = rows[0][0]['__row']
        fabrics = [(r, m) for r, m in rows if m and m.get('type') in ('fabric', 'yarn')]
        counts = Counter((m.get('type'), m.get('composition') or m.get('name')) for _, m in fabrics)
        if any(n > 3 for n in counts.values()):
            api.warn('10_BOM', rowno, f'{label}: >3 kain sejenis dalam satu grup; pastikan bukan pilihan warna yang dijumlahkan')
        colors = {api.s(m.get('color')).upper() for _, m in fabrics if api.s(m.get('color'))}
        if not ck and len(colors) > 1:
            api.warn('10_BOM', rowno, f'{label}: indikasi satu-baris-per-warna ({len(colors)} warna bahan); jangan menjumlahkan alternatif warna, isi kode_warna jika resep per warna')
        if not any(m and m.get('type') in ('accessory', 'packaging') for _, m in rows):
            api.warn('10_BOM', rowno, f'{label}: BOM tanpa aksesoris; HPP belum lengkap sampai kebutuhan label/benang/kancing dikonfirmasi')

    for (mk, sk, ck), lines in groups.items():
        rowno = lines[0]['source_row']
        label = f'{mk}/{sk}/{ck or "UMUM"}'
        codes = Counter(ln['code'] for ln in lines)
        if any(n > 1 for n in codes.values()):
            api.err('10_BOM', rowno, f'{label}: material muncul dua kali; gabungkan qty atau pisahkan kode_warna setelah konfirmasi')
            continue
        totals = Counter()
        for ln in lines:
            for target in ('kg', 'yard'):
                f = bom_uom.global_factor(ln['unit_base'], target)
                if f:
                    totals[target] += ln['qty_base'] * f
        problems = [extreme(q, u) for u, q in totals.items() if extreme(q, u)]
        if problems:
            api.err('10_BOM', rowno, f'{label}: total grup ' + '; '.join(problems))
            continue
        # API BOM dan pemilih varian memakai nama warna; kode disimpan juga untuk audit.
        color = api.s(color_docs.get(ck, {}).get('name')) if ck else ''
        if ck and not color:
            api.err('10_BOM', rowno, f"kode_warna '{ck}' tidak memiliki nama di master")
            continue
        # ── 2026-09-12 (keputusan owner): baris KAIN ROLL → 1 pcs POTONGAN ───────────
        # Kolom kain (kg/yard) di template hanya menyebut kain ASAL potongan; angka
        # kg/pcs tidak lagi menjadi dasar HPP (menyesatkan). Master potongan
        # `CUT-<MODEL>-<WARNA>-<UKURAN>` dibuat/dipakai-ulang lewat SSOT.
        lines = await panelize_lines(db, lines, mk, sk, ck, color, mdl, siz, apply, api, rowno, label)
        if lines is None:
            continue
        color_q = {'color': {'$in': list({color, ck})}} if ck else {'color': {'$in': ['', None]}}
        query = {'model_id': mdl[mk], 'size_id': siz[sk], 'active': True, **color_q}
        existing = await db.rahaza_boms.find(query, {'_id': 0}).to_list(1000)
        active = [b for b in existing if b.get('is_active', True)]
        if len(active) > 1:
            api.err('10_BOM', rowno, f'{label}: beberapa BOM aktif; bereskan versi di layar sebelum impor')
            continue
        old = active[0] if active else None
        if old and (not str(old.get('import_source', '')).startswith('master_template_') or
                    (old.get('import_fingerprint') and old['import_fingerprint'] != fingerprint(old))):
            api.err('10_BOM', rowno, f'{label}: BOM manual/hasil edit dilindungi, tidak ditimpa; tinjau dari layar BOM')
            continue
        version = old.get('version', 1) if old else max(
            [int(str(b.get('version', 0)).lstrip('vV') or 0) for b in existing] + [0]) + 1
        doc = {'model_id': mdl[mk], 'size_id': siz[sk], 'color': color, 'color_code': ck,
               'version': version, 'is_active': True, 'active': True, 'materials': lines,
               'notes': f'Impor master — {label}, {len(lines)} baris',
               'import_source': 'master_template_v2'}
        doc['import_fingerprint'] = fingerprint(doc)
        find = {'id': old['id']} if old else {**query, 'version': version}
        await api.upsert(db, 'rahaza_boms', find, doc, apply, '10_BOM')