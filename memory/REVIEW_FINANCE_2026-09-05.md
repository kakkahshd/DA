# REVIEW FINANCE & AUTO-JURNAL — 2026-09-05 (Iter 119, review saja — TANPA perubahan kode)

> Konteks: audit 2026-09-04 (`AUDIT_FINANCE_AKUNTING_2026-09-04.md`) menemukan 6 CRITICAL · 10 HIGH · 9 MED · 5 LOW.
> Iter 108–118 mengeksekusi sebagian besar. Review ini memverifikasi ulang dengan **membaca kode terbaru** +
> **uji nyata di API** (backend hidup, DB `backups/auto_20260902_190000` + migrasi startup) + **regresi pytest**.
>
> Hasil regresi: `tests/test_iter108…118 + iter96` → **111 PASS**, 22 gagal SEMUA karena login akun role
> `gudang@dewiaditya.id` 429 (akun role belum di-seed di container ini — bukan logika finance).
> `audit_finance_integrity.py` → 0 JE tak seimbang, cermin konsisten, TB seimbang, `balance-sheet.balanced=true`.

## A. Status temuan audit lama (verifikasi ulang)

| ID | Temuan audit 09-04 | Status kini | Bukti |
|---|---|---|---|
| C-01 | Subledger AR/AP dibuka di akun anak, ditutup di kontrol | ✅ SELESAI | `_ar_account_for_invoice/_ap_account_for_invoice` + `gl_ar_account_code` tersimpan; uji: AR `1-1301-REV-DISC` → payment Cr `1-1301-REV-DISC` |
| C-02 | AP-dari-GR ke 6-2200 + AP dobel | ✅ SELESAI | GR `received` → Dr 1-1401/Cr 2-1150; AP-dari-GR `gl_debit_code=2-1150` |
| C-03 | Jahit CMT dobel, FG negatif | ⚠️ SEBAGIAN | Upah CMT internal → Dr 1-1403 WIP; WIP→FG = Σ `fg_cost_layers`. **Tetapi** komponen `internal_labor_cost`, `permak_cost`, `overhead_cost` di lapisan TIDAK pernah di-debit ke WIP (lihat B-05) |
| C-04 | Neraca tak seimbang (tipe CURRENT_ASSET/OTHER) | ✅ SELESAI | `_bs_type()`, `type_warnings=[]`, balanced=true |
| C-05 | Profil asset_disposal salah akun | ✅ SELESAI | profil 1-2500/1-2501 |
| C-06 | Maklon tidak ke GL | ✅ SELESAI | `post_maklon_ar_invoice` tolak draft, void+re-post bila nilai berubah; payment → `post_ar_payment` + cash movement |
| H-01 | Dua skema AR | ✅ SELESAI | `rahaza_ar_canonical.canon()`, satu aging |
| H-02 | Payroll komponen | ✅ SELESAI | `payroll_deduction_totals`, toleransi 0,01 |
| H-03 | Bayar CMT | ✅ SELESAI | `cmt-payments/{id}/pay`, disbursement + void |
| H-04 | Dua keluarga kode akun | ✅ SELESAI (COA) / ⚠️ profil lama | `LEGACY_CODE_MAP`, 66 akun legacy nonaktif. **Tapi** DB lama masih membawa default kas `1-1101` di 5 profil (lihat B-04) |
| H-05 | Kas/bank tidak sinkron | ⚠️ SEBAGIAN | Rekon bank per cash account ✅. **Namun** `rahaza_cash_accounts.balance` masih field `$inc` manual (10 tempat), saldo kas dashboard = Σ field ini, bukan GL (lihat B-06) |
| H-06 | Rekon bank GL kosong | ✅ SELESAI | `gl_lines` per akun bank sesi, SSOT jurnal tak ditulisi |
| H-07 | Pendapatan PO internal | ✅ DICABUT (keputusan bisnis iter 115) | dispatch internal = handover, COGS lahir saat terjual |
| H-08 | Kontrol periode | ✅ SELESAI | `_ensure_period_open` (masa depan +31 hari, auto-open tahun ±1, 423 closed) |
| H-09 | post-ar tidak reaktif | ✅ SELESAI | void + re-post bila `total_debit ≠ total` |
| H-10 | CN/diskon salah akun | ⚠️ SEBAGIAN | Diskon → 4-1300, CN → 4-1200 ✅. **PPN pada CN generik (`post_credit_note`) masih tidak dibalik** (CN retur marketing `tax_amount=0`; hanya jalur `sales_direct` yang membalik PPN) |
| M-01 | Nilai persediaan = unit_cost master | ⚠️ SEBAGIAN | Laporan Nilai Persediaan FG ✅. Jurnal MI/adjust/scrap/aksesoris **masih** `rahaza_materials.unit_cost` saat posting (bukan nilai lapisan/rata-rata saat transaksi) |
| M-02 | Dua mesin COGS | ✅ DISATUKAN | `post_cogs_shipment` & `post_cogs_on_buyer_dispatch` memakai `_fifo_rows_to_components` yang sama |
| M-03 | 7-120 bertipe EXPENSE | ❌ BELUM | Biaya CMT maklon masuk "Beban Operasional" di L/R, bukan HPP maklon |
| M-04 | Penalti CMT → pendapatan lain | ❌ BELUM | Cr 4-9000, `net_amount` tidak diperbarui |
| M-05 | Akun `other` dua arah di pencairan | ❌ BELUM | subsidi ongkir (Cr) & potongan lain (Dr) satu akun; JE draft tanpa notifikasi |
| M-06 | Default kredit Kas Kecil | ❌ BELUM di DB lama | lihat B-04 |
| M-07 | Overdue otomatis | ✅ SELESAI | cron `mark-overdue` |
| M-08 | Akun kontra `type_normal_mismatch` | ❌ BELUM | 11 akun masih mismatch (`1-211, 1-521, 1-531, 1-541, 1-551, 3-400, 4-140, 4-141, 4-230, 5-130, 5-260`) — L/R & neraca menghitung dengan rumus tipe, jadi angkanya benar, tapi TB "normal balance" menyesatkan |
| M-09 | Tutup tahun | ✅ SELESAI | `year-end` close/reverse, 3-2000 |
| L-01 | Dua `_gen_je_number` | ✅ AMAN | keduanya lewat `gen_prefixed_number` counter yang sama |
| L-02 | `post_production_variance`/`post_asset_acquisition` tanpa `return` | ❌ BELUM | pemanggil menerima `None` |
| L-03 | Kode akun hard-code | ⚠️ SEBAGIAN | `rahaza_payroll_runs.py:292` masih default `"1-1201"`; `marketing_settlements` pakai akun toko ✅ |
| L-04 | Dua master pelanggan | ⚠️ | `rahaza_customers` kini dipakai Sales Direct; klien maklon tetap `dewi_maklon_clients` (subledger tetap konsisten via `_resolve_ar_code(customer_id)`) |
| L-05 | cascade PO hapus mirror | tidak diuji ulang | — |

**Kesimpulan A:** mesin jurnal inti (`_create_posted_je`) tetap sehat dan 6 CRITICAL lama sudah tertutup/diputuskan. Yang tersisa dari audit lama: C-03 (sebagian), H-05 (sebagian), H-10 (PPN CN), M-01 (bahan), M-03, M-04, M-05, M-06, M-08, L-02, L-03.

---

## B. TEMUAN BARU (dari review ini — semua dibuktikan di API/kode)

### B-01 🔴 CRITICAL — AR manual dengan diskon: jurnal TIDAK SEIMBANG → invoice `issued` tanpa GL
- **Uji nyata:** `POST /api/rahaza/ar-invoices` items 10×100.000, `tax_pct=11`, `discount_amount=50.000` → doc `subtotal=1.000.000, tax=110.000, total=1.060.000`. `POST …/send` → status **issued**, `post_error = "Jurnal tidak seimbang. Dr 1.110.000 ≠ Cr 1.160.000"`, `gl_je_id=None`.
- **Sebab:** dua konvensi `subtotal`. `rahaza_finance.create_ar` menyimpan `subtotal` = **bruto** dan `total = subtotal + tax − discount`; sementara `post_ar_invoice` (sejak iter 118) menganggap `subtotal` = **neto** (Cr Pendapatan = subtotal + diskon). Selisih persis = diskon.
- **Dampak tambahan:** PPN dihitung dari bruto sebelum diskon (iter 118 memperbaikinya untuk nota Sales Direct saja, tidak untuk AR manual Finance) → PPN keluaran lebih saji.
- **Rekomendasi:** satu konvensi (`subtotal` = neto setelah diskon, `tax = neto × pct`, `total = neto + tax`) di `create_ar` + `_validate_tax_discount`; tambahkan uji "AR manual berdiskon → JE seimbang". (AP manual `create_ap` tidak punya diskon — tidak terdampak.)

### B-02 🔴 HIGH — Dua pembayaran AR/AP bernilai sama di tanggal sama (tanpa rekening kas) → yang kedua TIDAK dijurnal
- **Uji nyata:** `POST /ar-invoices/{id}/payment {amount:100000, date:2026-09-05}` dua kali → `paid_amount` 200.000, tetapi JE hanya SATU (`already_posted: true` pada panggilan kedua). Subledger 200k vs GL 100k.
- **Sebab:** `post_ar_payment`/`post_ap_payment` source_ref = `arpay:{inv_id}:{date}:{amount}` bila `movement_id` kosong (tidak memilih cash account). Idempotensi memakan pembayaran sah.
- **Rekomendasi:** endpoint payment WAJIB menghasilkan `payment_id` unik (simpan di `rahaza_ar_payments`/`rahaza_cash_movements`) dan mengirimkannya sebagai `movement_id` walau tanpa cash account; atau wajibkan `account_id` (pembayaran tanpa rekening kas seharusnya tidak ada).

### B-03 🔴 HIGH — Jurnal OTOMATIS bisa di-void dari layar Jurnal tanpa menyentuh dokumen sumber
- **Uji nyata:** `POST /api/rahaza/journals/{je_id}/void` pada JE `ar_invoice` → JE `voided`, cermin dihapus, **invoice tetap `issued`, `gl_je_id`/`gl_posted_at` tetap terisi**, `paid_amount` tetap. Tidak ada jalur re-post (hook auto-post hanya jalan bila `gl_je_id` kosong).
- **Sebab:** `rahaza_journals.void_journal` tidak memeriksa `source_module` (hanya `status`).
- **Rekomendasi:** tolak void untuk `source_module ≠ manual/general` (arahkan ke tombol batal/void di modul sumber), atau saat void bersihkan `gl_*` di dokumen sumber lewat registry `source_module → (collection, prefix)`.

### B-04 🔴 HIGH — Profil posting di DB lama masih default **Kas Kecil 1-1101** untuk 5 event (klaim PRD iter 108 "default kas → bank 1-1201" hanya berlaku untuk DB yang di-seed baru)
- **Bukti:** `audit_finance_integrity.py` di DB restore: `ar_payment.debit_cash_default=1-1101`, `ap_payment.credit_cash_default=1-1101`, `expense.credit_cash_default=1-1101`, `employee_loan_disbursement.credit_cash=1-1101`, `asset_disposal.debit_cash=1-1101`. Uji B-02: penerimaan piutang tanpa rekening → **Dr 1-1101 Kas Kecil**.
- **Sebab:** `upgrade_posting_profiles()` hanya memetakan `1-110 → 1-1101` lewat `LEGACY_CODE_MAP`; `PROFILE_CODE_FIXES` tidak memuat kunci kas ini, sedangkan `DEFAULT_PROFILES` sudah 1-1201.
- **Rekomendasi:** tambahkan 5 kunci ke `PROFILE_CODE_FIXES` (atau lebih baik: HAPUS konsep "default kas" — wajibkan `cash_account_id` di semua pembayaran, lihat B-06).

### B-05 🔴 HIGH — Model absorption HPP tidak lengkap: upah internal, permak & overhead keluar dari WIP tanpa pernah masuk WIP
- **Kode:** `core/fg_cost_layers.compute_batch_unit_cost` → `unit_cost = material + sewing + permak + internal_labor + overhead`. `post_wip_to_fg_on_cmt_receipt/job_complete` → **Dr 1-1404 / Cr 1-1403 = Σ total_cost lapisan** (semua komponen). Yang masuk WIP (debit) hanya: MI bahan (`post_inventory_issue`, nilai `unit_cost` master) + AP CMT internal (`post_cmt_ap_invoice` → 1-1403). Tidak ada `Dr WIP` untuk `internal_labor_cost` (gaji cutting masuk 6-2100 Beban Gaji), `permak_cost` (`dewi_cmt_permak` tidak dijurnal sama sekali), `overhead_cost`.
- **Dampak:** (1) 1-1403 WIP bersaldo **kredit** sebesar komponen itu; (2) upah internal **dobel** — sebagai Beban Gaji (opex) DAN sebagai HPP saat terjual; (3) selisih bahan BOM vs MI aktual menumpuk di WIP tanpa jurnal variansi (sudah dicatat sebagai backlog "jurnal variansi WIP").
- **Rekomendasi:** putuskan per komponen: (a) applied overhead/labor → `Dr 1-1403 / Cr 5-3500 (BOP dibebankan)` & `Cr 6-2100`-reclass saat FG diterima; atau (b) keluarkan `internal_labor/overhead` dari nilai GL lapisan (tetap ada untuk analitik HPP), dan jurnal permak → `Dr 1-1403 / Cr Hutang vendor`. Tambahkan gate "saldo 1-1403 ≥ 0 & = Σ lapisan belum jadi".

### B-06 🟠 HIGH — Dua sumber kebenaran saldo kas/bank tetap ada (H-05 belum tuntas)
- `rahaza_cash_accounts.balance` di-`$inc` manual di 10 tempat (`rahaza_finance`, `dewi_maklon_finance`, `sales_direct`, `rahaza_petty_cash`, `dewi_bank_reconciliation`, `rahaza_bank_recon`), TIDAK di-`$inc` oleh: pembayaran gaji (`payroll_payment`), bayar BPJS/PPh21, pencairan marketplace, transfer bank (`bank_transfer`), klaim biaya/perjalanan. `opening_balance` tidak dijurnal. Dashboard `cash_balance` = Σ field `balance` (`rahaza_finance.py:1037`).
- **Dampak:** kartu kas ≠ GL ≠ mutasi. Rekonsiliasi bank memakai GL (benar), tetapi layar kas memakai field.
- **Rekomendasi:** hitung saldo kartu kas dari `rahaza_journal_lines` per `gl_account_code` (satu fungsi), hapus semua `$inc balance`; wajibkan `cash_account_id` pada semua jurnal yang menyentuh kas/bank (payroll, BPJS, settlement pakai akun toko → petakan ke cash account).

### B-07 🟠 HIGH — Potongan kasbon di payroll TIDAK pernah memangkas saldo kasbon & tidak memindah 2-1200 → 1-1320
- **Kode:** `rahaza_payroll_shared` (baris 461–483) memotong **seluruh outstanding** kasbon tiap payslip; `post_payroll_run` `Cr 2-1200` porsi kasbon dengan catatan "dipindah ke piutang oleh modul kasbon". Tetapi finalize payroll **tidak memanggil** `dewi_kasbon.apply_payroll_deductions` (endpoint ada, tanpa pemanggil backend/frontend) dan tidak ada yang mengubah `outstanding_balance`.
- **Dampak:** (1) kasbon yang sama dipotong LAGI di run berikutnya (outstanding tidak turun) — merugikan karyawan; (2) 2-1200 Hutang Gaji tersisa sebesar kasbon selamanya; 1-1320 tidak berkurang.
- **Rekomendasi:** finalize payroll → panggil `apply_payroll_deductions` (per `kasbon_id`, `amount` dari payslip, idempoten per periode — sudah ada) dalam transaksi yang sama; gate "Σ 2-1200 setelah bayar gaji = 0".

### B-08 🟠 HIGH — Retur marketplace dibukukan DUA KALI & menggantung di piutang fiktif
- `marketing_returns_routes.create_credit_note` → CN `Dr 4-1200 Retur / Cr AR pelanggan "MARKETPLACE"` (subledger dibuat otomatis). Padahal pendapatan marketplace hanya lahir dari **pencairan** (`marketing_settlements.create_draft_journal`) yang **sudah** memuat baris `refunds → Dr 4-1200`. Tidak pernah ada AR invoice untuk pelanggan MARKETPLACE.
- **Dampak:** retur terhitung 2× di 4-1200; `1-1301-MARKETPLACE` bersaldo **kredit** permanen; aging piutang tercemar. Barang retur yang masuk gudang (`wh_returns` → `stock_service.add`) juga **tanpa jurnal Dr FG / Cr HPP dan tanpa lapisan biaya** → stok FG naik, GL 1-1404 tidak (laporan Nilai Persediaan FG akan menandai "belum terjelaskan" terus).
- **Rekomendasi:** matikan/ubah CN retur marketplace menjadi pencatatan operasional saja (nilai refund dicocokkan ke baris `refunds` pencairan); retur fisik → `push_layer` HPP saat keluar + JE `Dr 1-1404 / Cr 5-xxxx` (pola sudah ada di `sales_direct.create_return`).

### B-09 🟡 MED — Tagihan CMT tidak otomatis masuk GL saat diterbitkan
- `post_cmt_ap_invoice` hanya dipanggil oleh `POST …/cmt-payments/{id}/post-ap` (manual) dan `…/pay`. Bridge (`production_maklon_bridge.py:438`) membuat `dewi_cmt_payments` `draft` tanpa JE. Tanggal JE = `payment_date`, bukan tanggal tagihan/penerimaan FG.
- **Dampak:** upah jahit masuk WIP terlambat (bisa sesudah FG diterima → WIP kredit sementara); beban maklon 7-120 diakui di periode bayar (kas), bukan periode jasa (akrual). Sisi kasnya (`pay`) tidak ada tanpa langkah Finance.
- **Rekomendasi:** post AP CMT saat status tagihan `approved/issued` (tanggal tagihan/`qc_completed_at`), bukan saat bayar.

### B-10 🟡 MED — GRNI (2-1150) bisa bersaldo permanen
- (a) `create_ap_from_gr` mengizinkan `unit_price` override ≠ harga GR → selisih tidak pernah dibersihkan (tidak ada jurnal selisih harga beli); (b) GR yang `received` **sebelum** iter 108 tidak punya JE GR, tetapi AP-dari-GR-nya kini `Dr 2-1150` → GRNI **debit** warisan; (c) baris GR tanpa `material_id`/`unit_price` tidak dijurnal tetapi tetap ditagih.
- **Rekomendasi:** jurnal selisih harga (`Dr/Cr 5-xxxx PPV`) saat AP ≠ GR; skrip backfill JE GR untuk GR lama yang sudah ada AP-nya; laporan "GRNI terbuka per GR".

### B-11 🟡 MED — Pembayaran AP bisa dicatat untuk invoice **draft** → invoice ikut diposting diam-diam
- `record_ap_payment` hanya menolak `cancelled/void/written_off`; bila `gl_je_id` kosong ia memanggil `post_ap_invoice` untuk invoice draft.

### B-12 🟡 MED — Jurnal bahan (MI/adjust/scrap/aksesoris) memakai `unit_cost` master saat posting (M-01 sisi bahan)
- Harga master berubah (rata-rata bergerak dari GR) ⇒ nilai keluar bahan tidak sama dengan nilai masuknya; 1-1401 bisa bersaldo ≠ Σ stok × biaya. Sudah ada mesin rata-rata (`core/accessory_valuation`) — pakai nilai pada saat transaksi & simpan `unit_cost_applied` di MI.

### B-13 🟢 LOW (laten) — L/R mengecualikan akun nonaktif
- `profit_loss` memfilter `active: True` (neraca sudah menyertakan akun nonaktif bersaldo). **Diukur di DB uji: 0 akun L/R nonaktif, 0 baris jurnal terdampak** — belum ada dampak nyata, tetapi menjadi bug begitu Finance menonaktifkan akun L/R yang pernah dijurnal. Samakan perilaku dengan neraca.

### B-14 🟢 LOW
- `post_production_variance` & `post_asset_acquisition` tidak `return result` (L-02 tetap).
- `rahaza_payroll_runs.py:292` default `"1-1201"` hard-code; `pay-bpjs/pph21` memakai kode GL langsung tanpa cash movement.
- `_create_posted_je(allow_closed_period)` memakai pencocokan string `"sudah"` pada pesan error — rapuh bila pesan diubah.
- `post_credit_note` generik tidak membalik PPN (H-10 sisa) — CN Finance/marketing dengan `tax_amount>0` akan membebani 4-1200 termasuk PPN.
- `scripts/audit_finance_live.py` sudah basi (`KeyError: 'assets'` karena bentuk respons neraca berubah) — perbarui agar alat audit bisa dipakai lagi.
- Seed `seed_role_accounts.py` wajib dijalankan sesudah restore; tanpa itu 22 uji RBAC finance 429/lockout (bukan bug finance).

---

## C. Yang terbukti BENAR (tidak perlu tindakan)
- `_create_posted_je`: seimbang, akun aktif & non-header, baris nol dilewati, idempoten per `(source_module, source_ref)`, cermin hanya `posted`, void hapus cermin, periode dijaga (masa depan, closed/locked, auto-open tahun ±1).
- COGS: satu rumus `_fifo_rows_to_components` untuk dispatch buyer, fulfillment online, Sales Direct; `basis` & `uncosted_qty` jujur; `zero_cogs` tidak diam.
- WIP→FG idempoten per receipt/job, lapisan ditandai `gl_je_id` (tidak dobel antara receipt CMT & job complete).
- Maklon: AR/pembayaran/cancel/void tersambung GL dan cash movement; `post-ar` menolak draft.
- Payroll: komponen PPh21/BPJS/kasbon/lainnya dari SATU agregator, JE ditolak bila tidak konsisten; bayar BPJS/PPh21 memakai akun mapping.
- Tutup tahun ke 3-2000, L/R mengecualikan `year_end_close`, neraca memakainya.
- TB & Neraca seimbang di DB uji; `type_warnings=[]`, `orphan_account_lines=[]`.

## D. Urutan perbaikan yang disarankan
1. **B-01** (AR manual diskon) + **B-02** (idempotensi pembayaran) + **B-03** (void jurnal otomatis) — cacat integritas GL yang bisa terjadi setiap hari, perbaikan kecil.
2. **B-04** (profil kas DB lama) + **B-06** (saldo kas dari GL, wajib `cash_account_id`) — menuntaskan H-05/M-06.
3. **B-07** (kasbon payroll) — merugikan karyawan & Hutang Gaji tidak pernah nol.
4. **B-08** (retur marketplace dobel + stok retur tanpa nilai) + **B-09** (AP CMT akrual).
5. **B-05** (absorption lengkap / jurnal variansi WIP) — keputusan model biaya perlu konfirmasi pemilik.
6. **B-10…B-14**, sisa M-03/M-04/M-05/M-08/L-02/L-03.

Setiap langkah: uji end-to-end (`verify_finance_fixes.py` diperluas), `audit_finance_integrity.py` 0 temuan, `balance-sheet.balanced=true`, dan gate baru untuk B-02/B-03/B-07 (keadaan akhir: subledger = GL).
