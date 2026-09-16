"""withdrawal_import — pembaca laporan PENARIKAN saldo Shopee/TikTok → draf baris tahap 2.

Sama seperti impor dana dilepas: hasil parse hanya PRATINJAU. Setiap kolom yang dipakai
disebut namanya dan bisa diganti staf sebelum disimpan; baris yang statusnya bukan
"berhasil" ditandai, bukan dibuang diam-diam.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.marketing_import_engine import parse_table, parse_number, parse_date, _norm_header

ROLE_KEYWORDS: Dict[str, List[str]] = {
    "reference": ["id penarikan", "withdrawal id", "no penarikan", "nomor penarikan", "transaction id",
                  "id transaksi", "no referensi", "referensi", "reference", "statement id", "batch id"],
    "date": ["tanggal penarikan", "withdrawal date", "waktu penarikan", "tanggal transaksi",
             "transaction time", "tanggal", "date", "waktu", "time"],
    "amount": ["jumlah penarikan", "withdrawal amount", "jumlah", "amount", "nominal", "total", "penarikan"],
    "status": ["status"],
    "bank": ["rekening", "bank", "account"],
}
SUCCESS_TOKENS = ("berhasil", "success", "selesai", "completed", "sukses", "done", "paid", "dibayar")
FAIL_TOKENS = ("gagal", "failed", "batal", "cancel", "ditolak", "reject", "pending", "diproses", "processing")


def _match(norm: str, keywords: List[str]) -> bool:
    return any(_norm_header(k) in norm for k in keywords)


def _numeric(rows: List[dict], col: str) -> bool:
    seen = 0
    for r in rows[:50]:
        v = r.get(col)
        if v in (None, ""):
            continue
        seen += 1
        if parse_number(v)[0] is None:
            return False
    return seen > 0


def guess_mapping(headers: List[str], rows: List[dict]) -> Dict[str, Optional[str]]:
    mapping: Dict[str, Optional[str]] = {k: None for k in ROLE_KEYWORDS}
    used: set = set()
    for role in ("reference", "status", "bank", "date", "amount"):
        for h in headers:
            if h in used:
                continue
            n = _norm_header(h)
            if not _match(n, ROLE_KEYWORDS[role]):
                continue
            if role == "amount" and not _numeric(rows, h):
                continue
            if role == "date" and not any(parse_date(r.get(h))[0] for r in rows[:20] if r.get(h) not in (None, "")):
                continue
            mapping[role] = h
            used.add(h)
            break
    return mapping


def build_rows(rows: List[dict], mapping: Dict[str, Optional[str]]) -> List[dict]:
    out = []
    for i, r in enumerate(rows):
        d = parse_date(r.get(mapping.get("date") or ""))[0] if mapping.get("date") else None
        amt = parse_number(r.get(mapping.get("amount") or ""))[0] if mapping.get("amount") else None
        ref = str(r.get(mapping.get("reference") or "") or "").strip() if mapping.get("reference") else ""
        status = str(r.get(mapping.get("status") or "") or "").strip() if mapping.get("status") else ""
        bank = str(r.get(mapping.get("bank") or "") or "").strip() if mapping.get("bank") else ""
        s_norm = status.lower()
        reason = None
        if amt is None or abs(amt) < 0.01:
            reason = "nominal kosong/0"
        elif not d:
            reason = "tanggal tidak terbaca"
        elif s_norm and any(t in s_norm for t in FAIL_TOKENS) and not any(t in s_norm for t in SUCCESS_TOKENS):
            reason = f"status '{status}' bukan berhasil"
        out.append({
            "row": i + 1, "withdrawal_date": d.date().isoformat() if d else None,
            "amount": round(abs(amt), 2) if amt is not None else None,
            "reference": ref or None, "status": status or None, "bank": bank or None,
            "ok": reason is None, "reason": reason,
        })
    return out


def parse_withdrawal_report(raw: bytes, filename: str,
                            mapping: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
    headers, rows = parse_table(raw, filename)
    if not headers:
        raise ValueError("Baris header tidak ditemukan di berkas")
    if not rows:
        raise ValueError("Berkas tidak punya baris data (hanya header)")
    mp = guess_mapping(headers, rows)
    if mapping:
        mp.update({k: (v if v in headers else None) for k, v in mapping.items() if k in mp})
    if not mp.get("amount"):
        raise ValueError("Kolom nominal penarikan tidak dikenali — pilih kolomnya secara manual.")
    parsed = build_rows(rows, mp)
    joined = " ".join(_norm_header(h) for h in headers)
    platform = "shopee" if "shopee" in joined else "tiktok" if "tiktok" in joined else ""
    return {
        "filename": filename, "headers": headers, "row_count": len(rows),
        "mapping": mp, "platform_guess": platform, "rows": parsed,
        "sample": rows[:3],
        "total_ok": round(sum(r["amount"] or 0 for r in parsed if r["ok"]), 2),
    }
