#!/usr/bin/env python3
"""verify_laporan_keuangan_ext.py — GATE **INV-F48** (2026-09-12): LAPORAN 12 BULAN · NERACA LAJUR ·
SALDO AWAL LEWAT LAYAR · ARUS KAS PER AKUN (OPR/INV/PND) — semua dari SATU buku besar.

  L1  Template saldo awal terunduh (xlsx, sheet SALDO_AWAL + 4 rincian relasi)
  L2  Pratinjau menolak: header diisi, akun L/R, D≠K tanpa opsi; menerima dengan tutup selisih ke 3-2000
  L3  Posting saldo awal → SATU jurnal `opening_balance` terkunci; posting kedua ditolak 409
  L4  Neraca saldo & neraca lajur: saldo awal muncul sebagai opening (from > tgl OB), kolom Neraca seimbang, laba bersih = L/R
  L5  Laba rugi 12 bulan: angka bulan = jurnal bulan itu; total = Σ bulan; akumulasi benar; sama dgn /profit-loss
  L6  Neraca 12 bulan: tiap kolom Aset = Liabilitas + Ekuitas (+ laba berjalan); kolom Des = /balance-sheet
  L7  Arus kas: by_account OPR/INV/PND dari akun lawan = perubahan kas GL; setiap akun aktif punya tag; PUT tag divalidasi
  L8  Ekspor Excel 4 laporan = angka layar (dibaca ulang dgn openpyxl)
  L9  Bersih: jurnal uji di-void/dihapus, mirror baris hilang, saldo kembali seperti sebelum uji
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
import uuid
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lib.gr_common import api_base, db_handle, http, login  # noqa: E402

G, R, X = "\033[92m", "\033[91m", "\033[0m"
PASS: list[str] = []
FAIL: list[str] = []
TAG = f"gate-f48-{uuid.uuid4().hex[:6]}"


def ok(k, m, d=""):
    PASS.append(k); print(f"  {G}✓{X} {k} {m}" + (f" · {d}" if d else ""))


def bad(k, m, d=""):
    FAIL.append(k); print(f"  {R}✗{X} {k} {m}" + (f" · {d}" if d else ""))


def check(k, cond, m, d=""):
    (ok if cond else bad)(k, m, d)


def get(path, tok):
    st, body = raw(path, tok)
    txt = body.decode("utf-8", "replace")
    return st, (json.loads(txt) if txt.startswith(("{", "[")) else txt)


def raw(path, tok, method="GET", body=None, headers=None):
    url = api_base() + "/api" + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {tok}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def multipart(fields: dict, filename: str, content: bytes):
    b = f"----{uuid.uuid4().hex}"
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
              f"Content-Type: application/octet-stream\r\n\r\n".encode())
    out.write(content)
    out.write(f"\r\n--{b}--\r\n".encode())
    return out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={b}"}


def fill(template: bytes, values: dict) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(template))
    ws = wb["SALDO_AWAL"]
    for row in ws.iter_rows(min_row=2):
        code = row[0].value
        if code in values:
            d, c = values[code]
            row[5].value, row[6].value = d, c
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def main() -> int:
    try:
        return run()
    finally:
        db = db_handle()
        ids = [j["id"] for j in db.rahaza_journal_entries.find({"memo": {"$regex": TAG}}, {"id": 1})]
        if ids:
            db.rahaza_journal_entries.delete_many({"id": {"$in": ids}})
            db.rahaza_journal_lines.delete_many({"je_id": {"$in": ids}})
            print(f"  (pembersihan darurat: {len(ids)} jurnal uji dihapus)")


def run() -> int:
    tok = login()
    if not tok:
        print("backend/login tidak siap"); return 2
    db = db_handle()
    year = 2026
    ob_date, tx1, tx2 = f"{year}-01-01", f"{year}-02-10", f"{year}-03-05"
    je_ids: list[str] = []
    pre_ob = db.rahaza_journal_entries.find_one({"source_module": "opening_balance", "status": {"$ne": "voided"}})
    if pre_ob:
        print(f"  (ada jurnal saldo awal nyata {pre_ob['je_number']} — L2/L3 posting dilewati, laporan diuji apa adanya)")
    tb_before = get(f"/rahaza/finance/reports/trial-balance?to={year}-12-31", tok)[1]["totals"]

    # L1 template
    st, body = raw("/rahaza/finance/opening-balance/template", tok)
    wb = openpyxl.load_workbook(io.BytesIO(body)) if st == 200 else None
    check("L1", st == 200 and wb and {"SALDO_AWAL", "PIUTANG_PELANGGAN", "HUTANG_SUPPLIER"} <= set(wb.sheetnames),
          "template saldo awal terunduh", f"HTTP {st} sheets={wb.sheetnames if wb else '-'}")

    ob_je = None
    if not pre_ob and st == 200:
        # L2 pratinjau
        bad_file = fill(body, {"1-1000": (1, 0), "1-1101": (5_000_000, 0)})
        data, hdr = multipart({}, "x.xlsx", bad_file)
        st2, r2 = raw("/rahaza/finance/opening-balance/preview", tok, "POST", data, hdr)
        j2 = json.loads(r2)
        check("L2a", st2 == 200 and not j2["ok"] and any("HEADER" in e for e in j2["errors"]) and any("≠" in e for e in j2["errors"]),
              "pratinjau menolak header & D≠K", "; ".join(j2["errors"])[:160])
        good = fill(body, {"1-1101": (5_000_000, 0), "1-1301": (2_000_000, 0), "1-2300": (10_000_000, 0),
                           "2-1100": (0, 3_000_000), "3-1000": (0, 10_000_000)})  # selisih 4 jt → 3-2000
        data, hdr = multipart({"balance_to_retained": "true"}, f"{TAG}.xlsx", good)
        st3, r3 = raw("/rahaza/finance/opening-balance/preview", tok, "POST", data, hdr)
        j3 = json.loads(r3)
        check("L2b", st3 == 200 and j3["ok"] and j3["balancing"] and j3["balancing"]["credit"] == 4_000_000 and j3["totals"]["debit"] == j3["totals"]["credit"] == 17_000_000,
              "pratinjau menerima + selisih ke 3-2000", f"D={j3['totals'].get('debit')} K={j3['totals'].get('credit')} err={j3['errors']}")
        data, hdr = multipart({}, f"{TAG}.xlsx", good)
        st3b, r3b = raw("/rahaza/finance/opening-balance/preview", tok, "POST", data, hdr)
        check("L2c", st3b == 200 and not json.loads(r3b)["ok"], "tanpa opsi tutup selisih → ditolak")
        # L3 posting
        data, hdr = multipart({"balance_to_retained": "true", "ob_date": ob_date}, f"{TAG}.xlsx", good)
        st4, r4 = raw("/rahaza/finance/opening-balance/apply", tok, "POST", data, hdr)
        j4 = json.loads(r4)
        ob_je = j4.get("journal") if st4 == 200 else None
        if ob_je:
            je_ids.append(ob_je["id"])
        check("L3a", st4 == 200 and ob_je and ob_je["status"] == "posted" and (ob_je.get("flags") or {}).get("locked"),
              "posting saldo awal → jurnal posted & terkunci", f"HTTP {st4} {ob_je and ob_je['je_number']}")
        st5, r5 = raw("/rahaza/finance/opening-balance/apply", tok, "POST", data, hdr)
        check("L3b", st5 == 409, "posting kedua ditolak 409", f"HTTP {st5}")
        stS, jS = get("/rahaza/finance/opening-balance/status", tok)
        check("L3c", stS == 200 and jS["journal"] and jS["journal"]["id"] == ob_je["id"] and len(jS["lines"]) == 6, "status menampilkan jurnal & 6 baris")

    # jurnal transaksi uji: Feb penjualan tunai 1 jt (kas 1-1101 ← 4-1100); Mar beli aset tetap 300rb (1-2101 ← 1-1101); Mar bayar hutang bank 200rb (2-2101 ← 1-1101)
    def je(d, lines, memo):
        st, txt = http("POST", "/rahaza/journals", tok, {"date": d, "memo": f"{TAG} {memo}", "post": True, "lines": lines})
        j = json.loads(txt)
        if st in (200, 201):
            je_ids.append(j["id"])
        return st, j
    accs = {a["code"]: a for a in db.rahaza_coa_accounts.find({"code": {"$in": ["1-1101", "4-1100", "1-2300", "2-2101", "6-2400", "6-2100"]}}, {"_id": 0})}
    ln = lambda code, d, c: {"account_code": code, "account_name": accs[code]["name"], "account_type": accs[code]["type"], "debit": d, "credit": c}  # noqa: E731
    exp_code = "6-2400" if "6-2400" in accs else "6-2100"
    s1, _ = je(tx1, [ln("1-1101", 1_000_000, 0), ln("4-1100", 0, 1_000_000)], "penjualan tunai")
    s2, _ = je(tx2, [ln("1-2300", 300_000, 0), ln("1-1101", 0, 300_000)], "beli aset")
    s3, _ = je(tx2, [ln("2-2101", 200_000, 0), ln("1-1101", 0, 200_000)], "bayar hutang bank")
    s4, _ = je(tx2, [ln(exp_code, 150_000, 0), ln("1-1101", 0, 150_000)], "beban")
    check("L0", all(s in (200, 201) for s in (s1, s2, s3, s4)), "4 jurnal uji terposting", f"{s1},{s2},{s3},{s4} beban={exp_code}")

    # L4 neraca saldo & lajur
    _, tb = get(f"/rahaza/finance/reports/trial-balance?from={year}-02-01&to={year}-12-31", tok)
    row = {r["code"]: r for r in tb["rows"]}
    if ob_je:
        check("L4a", row.get("1-1101", {}).get("opening_debit") == 5_000_000, "saldo awal 1-1101 tampil sebagai opening", f"{row.get('1-1101')}")
    _, ws = get(f"/rahaza/finance/reports/worksheet?from={year}-01-01&to={year}-12-31", tok)
    g = ws["grand_totals"]; b = ws["balancing"]
    check("L4b", ws["balanced"] and g["pl_debit"] == g["pl_credit"] and g["bs_debit"] == g["bs_credit"],
          "neraca lajur: kolom L/R & Neraca seimbang setelah baris laba", f"{g}")
    _, pl = get(f"/rahaza/finance/reports/profit-loss?from={year}-01-01&to={year}-12-31", tok)
    check("L4c", b["net_income"] == pl["totals"]["net_income"], "laba bersih lajur = /profit-loss", f"{b['net_income']} vs {pl['totals']['net_income']}")
    check("L4d", all((r["statement"] == "pl") == (r["type"] in ("REVENUE", "OTHER_INCOME", "COGS", "EXPENSE", "OTHER_EXPENSE")) for r in ws["rows"]),
          "setiap akun masuk kolom L/R atau Neraca sesuai tipe")

    # L5 laba rugi 12 bulan
    _, p12 = get(f"/rahaza/finance/reports/profit-loss-monthly?year={year}", tok)
    rev = next((a for a in p12["groups"]["revenue"]["accounts"] if a["code"] == "4-1100"), None)
    net = p12["lines"]["net_income"]
    check("L5a", rev and rev["months"][1] >= 1_000_000 and rev["total"] == round(sum(rev["months"]), 2), "4-1100 Feb ≥ 1 jt & total = Σ bulan", f"{rev and rev['months'][:4]}")
    check("L5b", net["total"] == pl["totals"]["net_income"], "Σ laba bersih 12 bulan = /profit-loss tahun", f"{net['total']} vs {pl['totals']['net_income']}")
    cum = p12["lines"]["net_income_cumulative"]["months"]
    check("L5c", all(abs(cum[i] - round(sum(net["months"][:i + 1]), 2)) < 0.01 for i in range(12)), "akumulasi s/d bulan benar")

    # L6 neraca 12 bulan
    _, b12 = get(f"/rahaza/finance/reports/balance-sheet-monthly?year={year}", tok)
    _, bs = get(f"/rahaza/finance/reports/balance-sheet?as_of={year}-12-31", tok)
    check("L6a", b12["balanced"] and not any(b12["totals"]["diff"]), "tiap kolom bulan Aset = L + E", f"diff={b12['totals']['diff']}")
    check("L6b", b12["sections"]["assets"]["months"][11] == bs["totals"]["assets"] and b12["totals"]["current_earnings"][11] == bs["totals"]["current_earnings"],
          "kolom Des = /balance-sheet", f"{b12['sections']['assets']['months'][11]} vs {bs['totals']['assets']}")
    if ob_je:
        check("L6c", b12["sections"]["assets"]["months"][0] >= 17_000_000, "kolom Jan memuat saldo awal", f"{b12['sections']['assets']['months'][0]}")

    # L7 arus kas per akun
    _, cf = get(f"/rahaza/finance/reports/cash-flow?from={year}-01-01&to={year}-12-31", tok)
    ba = cf["by_account"]
    items = {i["code"]: (grp, i) for grp, gd in ba["groups"].items() for i in gd["items"]}
    check("L7a", "1-1101" in ba["cash_account_codes"], "1-1101 dikenali sebagai akun kas")
    check("L7b", items.get("4-1100", ("",))[0] == "OPR" and items.get("1-2300", ("",))[0] == "INV" and items.get("2-2101", ("",))[0] == "PND",
          "akun lawan terkelompok OPR/INV/PND", f"{ {k: v[0] for k, v in items.items()} }")
    check("L7c", abs(ba["totals"]["unexplained"]) < 0.01 and ba["totals"]["cash_gl_net_change"] == ba["totals"]["net_change_in_cash"],
          "Σ arus kas akun lawan = perubahan kas menurut GL", f"{ba['totals']}")
    if ob_je:
        check("L7g", ba["totals"]["opening_cash_gl"] == 5_000_000 and "3-1000" not in items and ba["totals"]["closing_cash_gl"] == 5_350_000,
              "saldo awal = kas awal (bukan arus kas periode); kas akhir = awal + arus", f"{ba['totals']['opening_cash_gl']} → {ba['totals']['closing_cash_gl']}")
    missing = db.rahaza_coa_accounts.count_documents({"active": True, "cash_flow_group": {"$nin": ["OPR", "INV", "PND"]}})
    check("L7d", missing == 0, "semua akun aktif punya tag kelompok arus kas", f"tanpa tag={missing}")
    acc_id = accs["4-1100"]["id"]
    stp, _ = http("PUT", f"/rahaza/coa/accounts/{acc_id}", tok, {"cash_flow_group": "XXX"})
    check("L7e", stp == 400, "PUT tag tidak valid → 400", f"HTTP {stp}")
    stp2, txt = http("PUT", f"/rahaza/coa/accounts/{acc_id}", tok, {"cash_flow_group": "OPR"})
    check("L7f", stp2 == 200 and json.loads(txt).get("cash_flow_group") == "OPR", "PUT tag valid tersimpan")

    # L8 ekspor excel = layar
    def xl(report, q):
        st, body = raw(f"/rahaza/finance/reports/export-xlsx?report={report}&{q}", tok)
        return st, (openpyxl.load_workbook(io.BytesIO(body), data_only=True) if st == 200 else None)
    st, w = xl("profit-loss-monthly", f"year={year}")
    vals = [r for r in w.worksheets[0].iter_rows(values_only=True) if r[1] == "LABA BERSIH"] if w else []
    check("L8a", st == 200 and vals and list(vals[0][2:14]) == net["months"], "Excel Laba-12 = layar", f"HTTP {st}")
    st, w = xl("balance-sheet-monthly", f"year={year}")
    vals = [r for r in w.worksheets[0].iter_rows(values_only=True) if r[1] == "Total Aset"] if w else []
    check("L8b", st == 200 and vals and list(vals[0][2:14]) == b12["sections"]["assets"]["months"], "Excel Neraca-12 = layar")
    st, w = xl("worksheet", f"from={year}-01-01&to={year}-12-31")
    vals = [r for r in w.worksheets[0].iter_rows(values_only=True) if r[1] == "TOTAL"] if w else []
    check("L8c", st == 200 and vals and list(vals[0][8:12]) == [g["pl_debit"], g["pl_credit"], g["bs_debit"], g["bs_credit"]], "Excel N-Lajur = layar")
    st, w = xl("cash-flow", f"from={year}-01-01&to={year}-12-31")
    check("L8d", st == 200 and w and len(w.worksheets) == 2 and w.worksheets[1].max_row > 2, "Excel Arus-K 2 sheet (kategori + akun)")

    return finish(db, je_ids, tok, year, tb_before)


def finish(db, je_ids, tok, year, tb_before) -> int:
    for jid in je_ids:
        db.rahaza_journal_entries.delete_one({"id": jid})
        db.rahaza_journal_lines.delete_many({"je_id": jid})
    left = db.rahaza_journal_entries.count_documents({"id": {"$in": je_ids}}) + db.rahaza_journal_lines.count_documents({"je_id": {"$in": je_ids}})
    tb_after = get(f"/rahaza/finance/reports/trial-balance?to={year}-12-31", tok)[1]["totals"]
    check("L9", left == 0 and tb_after == tb_before, "jurnal uji dihapus, saldo kembali", f"sisa={left} {tb_after == tb_before}")

    print(f"\n{'HIJAU' if not FAIL else 'MERAH'}: {len(PASS)} lulus · {len(FAIL)} gagal {FAIL}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
