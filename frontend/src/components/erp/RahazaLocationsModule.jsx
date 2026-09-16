import { useEffect, useState } from 'react';
import MasterDataCRUD from './MasterDataCRUD';

// Peran gudang = SSOT `core/location_resolver` (STORAGE_ROLES + EXEMPT_ROLES).
// Peran inilah yang dibaca stok jual katalog (karantina DIKECUALIKAN), retur, dan cutting.
const ROLE_OPTIONS = [
  { value: 'bahan', label: 'Bahan / Kain (storage)' },
  { value: 'aksesoris', label: 'Aksesoris (storage)' },
  { value: 'fg', label: 'Barang Jadi — ikut stok jual' },
  { value: 'sample', label: 'Sample (storage)' },
  { value: 'karantina', label: 'Karantina QC — TIDAK ikut stok jual' },
  { value: 'cutting', label: 'Area Cutting (WIP)' },
  { value: 'sewing', label: 'Area Sewing (WIP)' },
  { value: 'qc', label: 'Area QC (WIP)' },
  { value: 'packing', label: 'Area Packing (WIP)' },
];
const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS.map((o) => [o.value, o.label]));

export default function RahazaLocationsModule({ token }) {
  const [locs, setLocs] = useState([]);
  useEffect(() => {
    fetch('/api/rahaza/locations', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : [])
      .then(setLocs).catch(() => {});
  }, [token]);

  const gedungOptions = locs.filter(l => l.type === 'gedung' && l.active).map(l => ({ value: l.id, label: l.name }));

  return (
    <MasterDataCRUD
      title="Lokasi Gudang"
      description="Gedung dan zona penyimpanan CV. Dewi Aditya beserta PERAN-nya. Peran menentukan perilaku stok: 'Barang Jadi' ikut stok jual katalog, 'Karantina QC' dikecualikan, 'Bahan/Kain' menjadi sumber Portal Cutting."
      endpoint="/api/rahaza/locations"
      token={token}
      testIdPrefix="rahaza-location"
      ieKey="locations"
      columns={[
        { key: 'code', label: 'Kode' },
        { key: 'name', label: 'Nama' },
        { key: 'type', label: 'Tipe', render: v => v === 'gedung' ? 'Gedung' : 'Zona' },
        { key: 'storage_role', label: 'Peran Gudang', render: v => (v ? (ROLE_LABEL[v] || v) : '—') },
        { key: 'parent_name', label: 'Induk (Gedung)', render: v => v || '-' },
      ]}
      fields={[
        { key: 'code', label: 'Kode', required: true, placeholder: 'Contoh: GD-L1-RAK atau GD-L1-QC' },
        { key: 'name', label: 'Nama', required: true, placeholder: 'Contoh: Gudang Lantai 1 — Rak / Karantina QC' },
        { key: 'type', label: 'Tipe', type: 'select', required: true,
          options: [{ value: 'gedung', label: 'Gedung' }, { value: 'zona', label: 'Zona' }] },
        { key: 'storage_role', label: 'Peran Gudang', type: 'select', options: ROLE_OPTIONS,
          help: 'Kosongkan untuk kantor / gedung konsep. Satu peran storage idealnya hanya dipegang satu lokasi aktif.' },
        { key: 'parent_id', label: 'Induk Gedung (khusus Zona)', type: 'select',
          options: gedungOptions, help: 'Isi hanya jika tipe = Zona.' },
      ]}
      defaultItem={{ code: '', name: '', type: 'zona', storage_role: '', parent_id: '' }}
    />
  );
}
