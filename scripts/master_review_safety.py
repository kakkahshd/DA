"""Pengaman dry-run dan artefak paket privat; tidak mengakses layanan eksternal."""
import hashlib
import json
import os
from pathlib import Path

from openpyxl import load_workbook
from master_template_spec import SHEETS

ROOT = Path(__file__).resolve().parents[1]
MASTER_COLLECTIONS = (
    'rahaza_locations', 'rahaza_employees', 'rahaza_payroll_profiles', 'rahaza_colors',
    'rahaza_sizes', 'rahaza_processes', 'rahaza_materials', 'rahaza_models', 'rahaza_boms',
    'vendor_partners', 'dewi_maklon_clients', 'marketing_platform_accounts',
    'marketing_catalog_items', 'marketing_kol_creators', 'marketing_livehosts',
    'users', 'da_payroll_allowances',
)


async def database_snapshot():
    """Bukti konteks master tanpa menyalin dokumen/kontak ke laporan atau menulis DB."""
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv(ROOT / 'backend/.env')
    client = AsyncIOMotorClient(os.environ['MONGO_URL'], serverSelectionTimeoutMS=10000)
    try:
        db = ReadOnlyDatabase(client[os.environ['DB_NAME']])
        snapshot = {}
        for name in MASTER_COLLECTIONS:
            rows = []
            async for doc in db[name].find({}, {'_id': 0}):
                rows.append(hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest())
            snapshot[name] = {'count': len(rows), 'sha256': hashlib.sha256(
                ''.join(sorted(rows)).encode()).hexdigest()}
        return snapshot
    finally:
        client.close()


class ReadOnlyCollection:
    """Hanya metode baca yang dipakai importir; mutasi gagal sebelum mengakses Mongo."""
    def __init__(self, collection):
        self._collection = collection

    def __getattr__(self, name):
        if name in {'find', 'find_one', 'count_documents', 'estimated_document_count'}:
            return getattr(self._collection, name)
        raise RuntimeError(f'Dry-run hanya-baca: operasi {name} ditolak')


class ReadOnlyDatabase:
    def __init__(self, database):
        self._database = database

    def __getitem__(self, name):
        return ReadOnlyCollection(self._database[name])

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def data_hash(path):
    """Hash nilai DAN tipe sel master; abaikan timestamp ZIP dan sheet audit."""
    wb = load_workbook(path, data_only=False, read_only=True)
    try:
        rows = {}
        for name in SHEETS:
            if name in wb:
                rows[name] = [[(cell.data_type, cell.value) for cell in row]
                              for row in wb[name].iter_rows()]
        return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                        default=str).encode('utf-8')).hexdigest()
    finally:
        wb.close()


def validate_paths(source, dest):
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if source.suffix.lower() != '.xlsx' or not source.is_file():
        raise ValueError('Sumber harus berkas .xlsx yang tersedia')
    if dest.exists():
        raise FileExistsError('Folder tujuan sudah ada; pilih folder baru agar paket lama tetap utuh')
    # uploads disajikan backend, public/build disajikan frontend.
    for public in (ROOT / 'frontend/public', ROOT / 'frontend/build', ROOT / 'uploads'):
        if dest == public.resolve() or public.resolve() in dest.parents:
            raise ValueError('Paket berisi data klien; folder publik/uploads tidak diizinkan')
    return source, dest