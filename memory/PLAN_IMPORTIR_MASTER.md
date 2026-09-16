# Rencana handoff importir master DAHOST

## Sumber dan batas pekerjaan
Dokumen yang disebut dalam handoff tidak ada di GitHub main e44c972. Rencana ini
direkonstruksi dari permintaan pengguna, bukan diklaim sebagai dokumen sesi lama.
Pengguna menyetujui Fase 1–6 dan default K1–K4. **Tidak boleh apply data produksi.**
Berkas asli: `uploads/template_client.xlsx`; selalu dipertahankan byte-identik.

## Keputusan tetap
- K1: `kode_warna` di BOM opsional; diisi = BOM per warna, kosong = umum.
- K2: konversi sedimensi memakai `core/bom_uom.py`; lintas cm→kg hanya dengan GSM dan lebar valid.
- K3: >5 kg atau >10 yard per pcs ditolak; >3 kain sejenis/grup, satu-baris-per-warna,
  dan BOM tanpa aksesoris diperingatkan. Tidak menebak resep yang benar.
- K4: `kode_karyawan` adalah kode internal, bukan NIK KTP; alias lama tetap diterima;
  nilai 16 digit ditolak dan tidak dimunculkan penuh dalam laporan.

## Urutan dan kriteria selesai
1. Kewajaran BOM: qty ekstrem ditolak, kasus DA-1502/XL dan 465 kg muncul eksplisit.
2. Spec/generator/importir selaras per warna; idempoten di DB uji, BOM manual tidak ditimpa; cek UI.
3. Satuan sedimensi/lintas dimensi terkendali; qty asal dan jejak konversi tersimpan.
4. Header karyawan kanonik + kompatibilitas alias dan penolakan NIK KTP.
5. Autofix konservatif, 13 aturan terdokumentasi, LOG_PERUBAHAN + isu ambigu;
   jalankan dua kali untuk idempotensi; sasaran 1.990→<700 kesalahan, laporkan angka nyata.
6. Paket klien berisi hasil autofix, review hasil, enam pertanyaan berbukti nomor baris.
7. DITAHAN: jawaban klien → dry-run nol kesalahan → backup penuh → apply → apply ulang →
   >=364 SKU, >=104 BOM, HPP >0, katalog 692 baris, harga_coret >= harga_jual, neraca/UI.

## Mitigasi
- Tidak membuat bahan, harga, GSM, lebar, identitas karyawan, atau warna resep berdasarkan tebakan.
- Autofix hanya berdasarkan master unik dan pola deterministik; konflik tetap perlu klien.
- Semua pengujian apply hanya DB uji terpisah memakai MONGO_URL lingkungan yang tersedia.
- Tidak mengubah fitur ERP lain atau melakukan audit baru di luar lingkup.

## Status sesi
Pengembangan dimulai; hasil tes dan angka autofix akan dicatat setelah terverifikasi.