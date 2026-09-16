#!/usr/bin/env python3
"""Susun paket klien privat dari autofix dan dry-run; tidak memiliki opsi apply."""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_master_template as importer
from autofix_master_template import build
from master_autofix_rules import redact
from master_client_documents import write_answers, write_json, write_questions, write_readme
from master_client_questions import build_questions, catalog_analysis
from master_review_safety import data_hash, file_hash, validate_paths, database_snapshot
from master_template_spec import SHEETS
from openpyxl import load_workbook


async def review(path, output):
    code = await importer.main(path, False, set(), output)
    return {'kesalahan': [[sh, row, redact(msg)] for sh, row, msg in importer.ERRORS],
            'peringatan': [[sh, row, redact(msg)] for sh, row, msg in importer.WARNINGS],
            'rencana': deepcopy(importer.STATS), 'exit_code_validator': code}


async def _build_package(source, dest, source_hash, historical_errors):
    database_before = await database_snapshot()
    fixed = dest / 'MASTER_CLIENT_AUTOFIX.xlsx'
    changes = build(source, fixed)
    before = await review(source, dest / 'REVIEW_SEBELUM_AUTOFIX.xlsx')
    after = await review(fixed, dest / 'REVIEW_SETELAH_AUTOFIX.xlsx')
    rerun = dest / 'MASTER_CLIENT_AUTOFIX_ULANG.xlsx'
    repeated = build(fixed, rerun)
    fixed_hash, rerun_hash = data_hash(fixed), data_hash(rerun)
    if repeated['perubahan'] or fixed_hash != rerun_hash:
        raise RuntimeError('Autofix tidak idempoten; paket tidak diterbitkan')
    wb = load_workbook(fixed, data_only=True)
    try:
        missing = [name for name in SHEETS if name not in wb]
        if len(missing) == len(SHEETS):
            raise ValueError('Tidak ditemukan sheet master yang dikenali')
        catalog = catalog_analysis(wb)
        questions = build_questions(wb, after, catalog)
    finally:
        wb.close()
    errors, warnings = after['kesalahan'], after['peringatan']
    database_after = await database_snapshot()
    if database_before != database_after:
        raise RuntimeError('Master database berubah selama pemeriksaan; ulangi saat kondisi stabil')
    summary = {
        'tanggal_utc': datetime.now(timezone.utc).isoformat(), 'source': source.name,
        'source_sha256': source_hash, 'source_unchanged': file_hash(source) == source_hash,
        'historical_errors': historical_errors,
        'errors_before_current_validator': len(before['kesalahan']), 'errors_after': len(errors),
        'warnings_after': len(warnings), 'errors_by_sheet': dict(Counter(e[0] for e in errors)),
        'error_locations_after': len({(e[0], e[1]) for e in errors}),
        'missing_sheets': missing, 'changes': changes['perubahan'],
        'changes_second_run': repeated['perubahan'], 'data_idempotent': fixed_hash == rerun_hash,
        'data_sha256': fixed_hash, 'data_sha256_second_run': rerun_hash,
        'catalog_rows': catalog['rows'], 'catalog_unique_account_sku': catalog['unique_account_sku'],
        'catalog_duplicate_groups': len(catalog['duplicate_groups']),
        'catalog_conflicting_groups': catalog['conflicting_groups'],
        'catalog_incomplete_rows': len(catalog['incomplete_rows']),
        'target_under_700_met': len(errors) < 700,
        'apply_performed': False, 'database_access': 'read_only',
        'database_unchanged': True, 'database_review_snapshot': database_before,
        'phase_7': 'DITAHAN — jawaban klien, dry-run 0 kesalahan, review peringatan dan persetujuan owner diperlukan'}
    if not summary['source_unchanged']:
        raise RuntimeError('Sumber berubah selama pemeriksaan; ulangi dengan salinan stabil')
    write_json(dest / 'HASIL.json', summary)
    write_json(dest / 'KESALAHAN.json', {'sebelum': before, **after})
    write_json(dest / 'PERTANYAAN_KLIEN.json', questions)
    write_json(dest / 'KATALOG_DUPLIKAT.json', catalog)
    write_questions(dest, summary, questions)
    write_answers(dest, questions, catalog)
    write_readme(dest, summary)
    files = {p.name: {'sha256': file_hash(p), 'bytes': p.stat().st_size}
             for p in sorted(dest.iterdir()) if p.is_file()}
    write_json(dest / 'MANIFEST.json', {'source_sha256': source_hash, 'files': files})
    for path in dest.iterdir():
        path.chmod(0o600)
    return summary


async def package(source, dest, historical_errors=None):
    source, dest = validate_paths(source, dest)
    if historical_errors is not None and historical_errors < 0:
        raise ValueError('Angka historis tidak boleh negatif')
    source_hash = file_hash(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Seluruh artefak dibuat di staging privat. Kesalahan tidak meninggalkan paket setengah jadi.
    with tempfile.TemporaryDirectory(prefix=f'.{dest.name}-', dir=dest.parent) as temporary:
        staging = Path(temporary)
        summary = await _build_package(source, staging, source_hash, historical_errors)
        # Reservasi eksklusif: menolak folder yang dibuat proses lain selama build.
        dest.mkdir(mode=0o700, exist_ok=False)
        try:
            os.replace(staging, dest)
        except OSError:
            dest.rmdir()
            raise
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('output_directory', type=Path, help='Folder privat BARU; tidak menimpa paket lama')
    ap.add_argument('--historical-errors', type=int, default=None,
                    help='Angka historis dari laporan lama; tidak dianggap hasil validator saat ini')
    args = ap.parse_args()
    try:
        asyncio.run(package(args.source, args.output_directory, args.historical_errors))
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        ap.exit(1, f'Paket tidak dibuat: {exc}\n')