"""Enam kelompok keputusan klien berdasarkan temuan aktual, bukan nomor baris tetap."""
from collections import defaultdict

from autofix_master_template import records
from import_master_template import s, num, is_num
from master_autofix_rules import redact
from master_import_bom import extreme


def catalog_analysis(wb):
    rows = list(records(wb['14_KATALOG_JUAL'])) if '14_KATALOG_JUAL' in wb else []
    groups = defaultdict(list)
    incomplete = []
    for row, record in rows:
        key = tuple(s(record.get(k)).upper() for k in ('kode_akun', 'sku'))
        if not all(key):
            incomplete.append(row)
            continue
        groups[key].append((row, record))
    duplicates = []
    fields = ('harga_jual', 'harga_coret', 'tautan_produk', 'aktif', 'nama_tampil')
    for (account, sku), entries in sorted(groups.items()):
        if len(entries) < 2:
            continue
        def value(record, key):
            raw = record.get(key)
            return num(raw) if key.startswith('harga_') and is_num(raw) else s(raw)
        differences = [key for key in fields if len({value(r, key) for _, r in entries}) > 1]
        duplicates.append({'kode_akun': account, 'sku': sku, 'baris': [i for i, _ in entries],
                           'kolom_berbeda': differences,
                           'nilai': [{k: redact(r.get(k)) for k in fields} for _, r in entries]})
    return {'rows': len(rows), 'unique_account_sku': len(groups),
            'incomplete_rows': incomplete, 'duplicate_groups': duplicates,
            'duplicate_excess_rows': sum(len(d['baris']) - 1 for d in duplicates),
            'conflicting_groups': sum(bool(d['kolom_berbeda']) for d in duplicates)}


def _group(sheet, message):
    if sheet in ('13_AKUN_TOKO', '14_KATALOG_JUAL'):
        return 6
    if sheet == '07_AKSESORIS':
        return 4
    if sheet in ('01_LOKASI', '02_KARYAWAN', '05_PROSES', '11_VENDOR_CMT',
                 '12_KLIEN_MAKLON', '15_KOL_KREATOR', '16_LIVEHOST'):
        return 5
    if sheet == '10_BOM':
        if any(t in message for t in ('qty', 'gramasi', 'konversi', 'satuan', 'total grup')):
            return 2
        if any(t in message for t in ('kode_material', 'belum ada', 'tidak memiliki nama')):
            return 3
        return 1
    return 3


def build_questions(wb, review, catalog):
    groups = defaultdict(list)
    for kind in ('kesalahan', 'peringatan'):
        for sheet, row, message in review[kind]:
            groups[_group(sheet, message)].append(
                {'jenis': kind, 'sheet': sheet, 'baris': row, 'pesan': redact(message)})
    extremes = []
    if '10_BOM' in wb:
        for row, record in records(wb['10_BOM']):
            if is_num(record.get('qty_per_pcs')):
                qty = num(record['qty_per_pcs'])
                if extreme(qty, record.get('satuan')):
                    extremes.append({'model': s(record.get('kode_model')), 'baris': row,
                                     'qty': qty, 'satuan': s(record.get('satuan'))})
    titles = ['BOM per warna dan aksesoris', 'Qty nyata serta gramasi dan lebar',
              'Identitas bahan, warna dan SKU', 'Satuan kemasan dan harga aksesoris',
              'Lokasi, karyawan dan aturan insentif', 'Katalog per toko dan duplikasinya']
    prompts = [
        'Apakah setiap baris kain dipakai bersamaan atau merupakan pilihan warna? Isi kode_warna '
        'untuk resep khusus; kode_warna kosong tetap berarti BOM umum. Konfirmasikan kebutuhan '
        'label, benang dan kancing per pcs, serta BOM manual yang harus dipertahankan.',
        'Berapa qty komponen per pcs yang benar? Qty ekstrem tidak diubah skala tanpa konfirmasi. '
        'Untuk konversi panjang ke berat, isi gramasi_gsm dan lebar_cm. Untuk qty kosong atau '
        'rentang, berikan satu angka pasti beserta satuannya.',
        'Lengkapi kode bahan/warna/model/ukuran yang benar dan tentukan baris yang dipertahankan '
        'untuk kode atau SKU duplikat. Kode tidak diganti berdasarkan kemiripan nama. '
        'Lengkapi pula struktur sheet/kolom jika ditandai di temuan.',
        'Pilih satu satuan stok serta jumlah isi kemasan yang pasti untuk nilai ambigu. '
        'Apakah harga nol memang benar atau belum diisi? Harga harus per satuan stok, '
        'bukan harga paket dengan ukuran berbeda.',
        'Lengkapi master karyawan dan pemetaan host memakai kode internal, bukan NIK KTP. '
        'Benarkan tipe/induk lokasi dan rujukan operasional. Konfirmasikan aturan insentif '
        'kreator, termasuk kelayakan tipe new, jika ditandai.',
        f"Hasil pemisahan: {catalog['rows']} baris, {catalog['unique_account_sku']} pasangan toko–SKU "
        f"lengkap dan unik, {len(catalog['duplicate_groups'])} grup duplikat "
        f"({catalog['conflicting_groups']} berbeda isi), serta {len(catalog['incomplete_rows'])} baris "
        'dengan kunci tidak lengkap. Tentukan harga, tautan, dan baris yang benar untuk setiap '
        'konflik; jumlah pasangan unik bukan target final yang diputuskan otomatis. '
        'Tautan toko pertama tidak disalin ke toko kedua.'
    ]
    if extremes:
        by_value = defaultdict(list)
        for item in extremes:
            by_value[(item['model'], item['qty'], item['satuan'])].append(item['baris'])
        prompts[1] += ' Nilai ekstrem pada berkas ini: ' + '; '.join(
            f"{redact(model)}: {qty:g} {unit}, baris {', '.join(map(str, rows[:12]))}"
            + (f' (total {len(rows)} baris)' if len(rows) > 12 else '')
            for (model, qty, unit), rows in list(by_value.items())[:6]) + '.'
    return [{'id': f'Q{i}', 'judul': title, 'pertanyaan': prompts[i - 1],
             'status': 'PERLU JAWABAN' if groups[i] else 'TINJAU BISNIS',
             'temuan': groups[i]} for i, title in enumerate(titles, 1)]


def evidence_examples(findings, limit=6):
    """Variasikan pesan; qty ekstrem lebih dulu, bukan enam baris sejenis pertama."""
    ordered = sorted(findings, key=lambda f: ('qty ekstrem' not in f['pesan'], f['jenis'] != 'kesalahan'))
    chosen, seen = [], set()
    categories = ('qty ekstrem', 'total grup', 'gramasi', 'konversi', 'qty_per_pcs',
                  'isi_per_kemasan', 'satuan_dasar', 'harga_per_satuan', 'kode_karyawan',
                  'insentif', 'kode_induk', "'tipe'", 'tanpa aksesoris', 'pilihan warna',
                  'satu-baris-per-warna', 'kembar', 'konflik', 'kolom wajib', 'tidak ada baris')
    for item in ordered:
        kind = next((word for word in categories if word in item['pesan']), item['pesan'])
        signature = (item['sheet'], kind)
        if signature not in seen:
            chosen.append(item)
            seen.add(signature)
        if len(chosen) == limit:
            break
    if len(chosen) < limit:
        chosen += [item for item in ordered if item not in chosen][:limit - len(chosen)]
    return chosen