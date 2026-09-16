#!/usr/bin/env python3
"""scripts/reset_for_golive.py — KOSONGKAN data lama sebelum impor data nyata.

    python3 scripts/reset_for_golive.py                 # DRY-RUN: hanya melaporkan rencana
    python3 scripts/reset_for_golive.py --apply         # mongodump dulu, lalu hapus
    python3 scripts/reset_for_golive.py --apply --yes   # tanpa konfirmasi interaktif

Keputusan owner (2026-09): SEMUA koleksi dikosongkan KECUALI konfigurasi sistem:
  users (hanya superadmin dipertahankan), roles, role_permissions, COA + posting profiles,
  company_settings, master satuan gudang, penomoran dokumen, template PDF, konfigurasi
  notifikasi. Superadmin `admin@garment.com` tidak disentuh (sandi tetap).

Pengaman:
  * Dry-run bawaan; `--apply` WAJIB didahului mongodump ke /app/backups/pre_golive_<waktu>/
    (gagal backup = berhenti). Restore: `mongorestore --uri "$MONGO_URL" --db "$DB_NAME" <folder>`.
  * Koleksi yang dipertahankan dicetak eksplisit; tidak ada pola regex "kira-kira".
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = ROOT / "backups"

KEEP_COLLECTIONS = (
    "roles", "role_permissions", "role_access_overrides",
    "rahaza_coa_accounts", "rahaza_posting_profiles", "chart_of_accounts",
    "company_settings", "company_profile",
    "wh_unit_master", "wh_unit_conversions",
    "doc_number_configs", "pdf_templates",
    "notif_category_config", "notification_settings", "notification_providers",
    "backup_config",
)
SUPERADMIN_EMAIL = os.environ.get("SUPERADMIN_EMAIL", "admin@garment.com")
G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"


async def plan(db) -> tuple[list[tuple[str, int]], list[tuple[str, int]], int]:
    names = sorted(n for n in await db.list_collection_names() if not n.startswith("system."))
    wipe, keep = [], []
    for n in names:
        c = await db[n].count_documents({})
        (keep if n in KEEP_COLLECTIONS else wipe).append((n, c))
    other_users = await db.users.count_documents({"email": {"$ne": SUPERADMIN_EMAIL}})
    wipe = [(n, c) for n, c in wipe if n != "users"]
    return wipe, keep, other_users


def mongodump(uri: str, dbname: str) -> Path:
    dest = BACKUP_ROOT / f"pre_golive_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["mongodump", f"--uri={uri}", f"--db={dbname}", f"--out={dest}", "--gzip", "--quiet"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if res.returncode != 0 or not any((dest / dbname).glob("*.bson*")):
        raise SystemExit(f"{R}mongodump GAGAL — reset dibatalkan.{X}\n{res.stderr[-800:]}")
    return dest


async def main(apply: bool, yes: bool) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    from motor.motor_asyncio import AsyncIOMotorClient
    uri, dbname = os.environ["MONGO_URL"], os.environ["DB_NAME"]
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
    try:
        db = client[dbname]
        sa = await db.users.find_one({"email": SUPERADMIN_EMAIL}, {"_id": 0, "role": 1})
        if not sa or sa.get("role") != "superadmin":
            print(f"{R}Superadmin '{SUPERADMIN_EMAIL}' tidak ditemukan/bukan superadmin — reset ditolak "
                  f"agar sistem tidak kehilangan akses.{X}")
            return 1
        wipe, keep, other_users = await plan(db)
        print(f"{B}Basis data :{X} {dbname}\n{B}Mode       :{X} "
              + (f"{R}HAPUS (--apply){X}" if apply else f"{G}DRY-RUN (rencana saja){X}"))
        print(f"\n{B}DIPERTAHANKAN{X} ({len(keep)} koleksi)")
        for n, c in keep:
            print(f"  {n:36s} {c:7d}")
        print(f"  {'users (hanya superadmin)':36s} {1:7d}")
        print(f"\n{B}DIKOSONGKAN{X} ({len(wipe)} koleksi + {other_users} user non-superadmin)")
        total = other_users
        for n, c in wipe:
            total += c
            if c:
                print(f"  {n:36s} {c:7d}")
        print(f"\n  Total dokumen yang akan dihapus: {B}{total}{X}")
        if not apply:
            print(f"\n{G}Dry-run selesai — tidak ada yang diubah.{X} Jalankan dengan --apply untuk mengeksekusi.")
            return 0
        if not yes:
            ans = input(f"\nKetik {B}HAPUS{X} untuk melanjutkan (mongodump dibuat lebih dulu): ").strip()
            if ans != "HAPUS":
                print("Dibatalkan.")
                return 1
        dest = mongodump(uri, dbname)
        print(f"{G}Backup mongodump:{X} {dest}")
        removed = 0
        for n, c in wipe:
            if c:
                removed += (await db[n].delete_many({})).deleted_count
        removed += (await db.users.delete_many({"email": {"$ne": SUPERADMIN_EMAIL}})).deleted_count
        await db.login_attempts.delete_many({})
        print(f"\n{G}{B}RESET SELESAI.{X} {removed} dokumen dihapus. Koleksi konfigurasi dan superadmin utuh.")
        print(f"Pulihkan bila perlu: mongorestore --uri \"$MONGO_URL\" --gzip --nsInclude '{dbname}.*' "
              f"--drop {dest}")
        print(f"{Y}Restart backend setelah reset supaya seed startup (COA/roles/proses) berjalan ulang.{X}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true", help="lewati konfirmasi interaktif")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.yes)))
