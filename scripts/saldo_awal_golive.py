#!/usr/bin/env python3
"""saldo_awal_golive.py — TEMPLATE & IMPOR SALDO AWAL NERACA GO-LIVE (CLI).

  python3 scripts/saldo_awal_golive.py template private/golive/SALDO_AWAL_GOLIVE.xlsx
  python3 scripts/saldo_awal_golive.py import   private/golive/SALDO_AWAL_GOLIVE.xlsx --date 2026-10-01 [--balance-to-retained] [--apply]

Logika (template · pemeriksaan · posting) = `backend/core/opening_balance.py`, SAMA dengan layar
Portal Keuangan → Master Akuntansi → Saldo Awal. Skrip ini hanya pembungkus CLI.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from database import get_db  # noqa: E402  (memuat backend/.env)
from core import opening_balance as ob  # noqa: E402


async def make_template(dest: Path) -> int:
    data, n = await ob.build_template(get_db())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"Template saldo awal: {dest} · {n} akun neraca")
    return 0


async def do_import(src: Path, ob_date: str, apply: bool, balance_to_retained: bool) -> int:
    db = get_db()
    res = await ob.parse_workbook(db, src.read_bytes(), balance_to_retained)
    t = res["totals"]
    print(f"Saldo awal per {ob_date}: {t.get('lines', 0)} baris · D Rp {t.get('debit', 0):,.0f} · K Rp {t.get('credit', 0):,.0f} · rincian relasi: "
          + ", ".join(f"{r['sheet']} Rp {r['detail_total']:,.0f}" for r in res.get("relations", [])))
    if res["errors"]:
        print("\n".join("  ✗ " + e for e in res["errors"]))
        print("TIDAK ADA yang disimpan.")
        return 1
    if not res["lines"]:
        print("Semua saldo 0 — tidak ada jurnal pembuka yang perlu dibuat (boleh untuk mulai dari nol).")
        return 0
    if await ob.existing_opening(db):
        print("  ✗ Sudah ada jurnal saldo awal (opening_balance) yang aktif — void dulu bila ingin mengulang.")
        return 1
    if not apply:
        print("DRY-RUN bersih. Jalankan lagi dengan --apply untuk memposting jurnal pembuka.")
        return 0
    user = await db.users.find_one({"role": {"$in": ["superadmin", "super_admin"]}}, {"_id": 0, "id": 1, "name": 1}) or {"id": "system", "name": "saldo_awal_golive.py"}
    je = await ob.post_opening(db, user, ob_date, res["lines"], src.name)
    print(f"✓ Jurnal pembuka {je['je_number']} diposting ({len(res['lines'])} baris) dan dikunci.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "template":
        sys.exit(asyncio.run(make_template(Path(args[1]))))
    if len(args) >= 2 and args[0] == "import":
        date_ = args[args.index("--date") + 1] if "--date" in args else None
        if not date_:
            print("wajib --date YYYY-MM-DD (tanggal go-live)")
            sys.exit(2)
        sys.exit(asyncio.run(do_import(Path(args[1]), date_, "--apply" in args, "--balance-to-retained" in args)))
    print(__doc__)
    sys.exit(2)
