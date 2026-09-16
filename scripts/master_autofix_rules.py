"""Aturan murni autofix Excel. Tidak memakai fuzzy matching atau evaluasi kode."""
import ast
import math
import operator
import re
from decimal import Decimal

from core.bom_uom import global_factor, norm_unit

RULES = {
    'R01': 'Nama sheet kanonik jika pemetaan unik',
    'R02': 'Buang # pada kode data (bukan komentar/contoh dan bukan hex)',
    'R03': 'Trim teks dan pulihkan telepon numerik menjadi teks',
    'R04': 'Normalisasi ALL SIZE → ALLSIZE pada kode ukuran',
    'R05': 'Header kode_karyawan; header DONE diarsip, master tetap kosong',
    'R06': 'Nama warna → kode hanya bila rujukan master unik',
    'R07': 'Isi rujukan dan nama kosong dari SKU yang cocok master unik',
    'R08': 'Jenis kain dari istilah tekstil eksplisit, bukan tebakan satuan',
    'R09': 'Isi kemasan teks menjadi angka hanya bila unit sedimensi pasti',
    'R10': 'Aritmetika literal/formula dan qty komponen satu material+satuan',
    'R11': 'Tukar harga jual/coret hanya jika keduanya positif dan terbalik',
    'R12': 'Pecah akun katalog kedua dan pertahankan tautan per akun',
    'R13': 'Gabungkan duplikat master identik; konflik dan BOM tetap ditahan',
}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv}


def arithmetic(text):
    """Hanya angka dan + - * /; tanpa nama, fungsi, referensi sel, atau pangkat."""
    if not isinstance(text, str) or len(text) > 150:
        return None
    try:
        tree = ast.parse(text.lstrip('=').strip(), mode='eval')
        def walk(n):
            if isinstance(n, ast.Constant) and type(n.value) in (float, int):
                return Decimal(str(n.value))
            if isinstance(n, ast.BinOp) and type(n.op) in OPS:
                return OPS[type(n.op)](walk(n.left), walk(n.right))
            if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
                return walk(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
            raise ValueError('bukan aritmetika literal')
        result = float(walk(tree.body))
        return result if math.isfinite(result) else None
    except (SyntaxError, ValueError, TypeError, ArithmeticError, RecursionError):
        return None


def compound_qty(value, material_code, unit):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', str(material_code or '')):
        return None
    if norm_unit(unit) not in ('kg', 'gram', 'cm', 'm', 'yard', 'pcs'):
        return None
    # Daftar komponen positif (format klien "0,167 - 0,147 - 0,149").
    # Dua angka dengan dash ambigu rentang vs komponen: TIDAK dijumlahkan.
    parts = re.split(r'\s+\+\s+|\s+-\s+', value.strip())
    if ' - ' in value and len(parts) < 3:
        return None
    if len(parts) < 2 or not all(re.fullmatch(r'\d+(?:[.,]\d+)?', p) for p in parts):
        return None
    return float(sum(Decimal(p.replace(',', '.')) for p in parts))


def packaging(value, base):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)\s*', value)
    if not match:
        return None
    n, unit = match.groups()
    unit, base = norm_unit(unit), norm_unit(base)
    factor = global_factor(unit, base)
    if factor:
        return float(Decimal(n.replace(',', '.'))) * factor
    return None


def textile_kind(name, kind):
    kind = str(kind or '').strip().lower()
    if kind in ('fabric', 'yarn'):
        return kind
    if kind in ('knit', 'knit palmer', 'woven', 'rajut', 'kain'):
        return 'fabric'
    if kind in ('benang',):
        return 'yarn'
    if not kind and re.search(r'\b(kain|knit|rib|rayon|katun|cotton|linen|oxford|wolly|wolfis|shakila|shakilla|crinkle|satin|poplin|twill|denim|babyterry|fleece|hyget|hijetc|moscrepe)\b', str(name or ''), re.I):
        return 'fabric'
    return None


def redact(value):
    text = '' if value is None else str(value)
    return re.sub(r'(?<!\d)\d{16}(?:\.0)?(?!\d)', '[NIK KTP disamarkan]', text)