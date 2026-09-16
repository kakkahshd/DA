import { useState } from 'react';
import { Copy, PackagePlus, Calculator, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { GlassInput } from '@/components/ui/glass';
import { toast } from 'sonner';
import { InlineMaterialPicker } from './InlineMaterialPicker';

const post = (url, headers, body) => fetch(url, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
  .then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : j.detail?.message || `HTTP ${r.status}`); return j; });

// Jalan pintas pengisian BOM (owner 2026-09-12): salin ke varian tanpa BOM · aksesoris massal · HPP standar
export function BomShortcuts({ headers, token, selectedModelId, modelLabel, categories, onDone }) {
  const [busy, setBusy] = useState('');
  const [accOpen, setAccOpen] = useState(false);
  const [lines, setLines] = useState([]);

  const copyMissing = async (all) => {
    setBusy('copy');
    try {
      const r = await post('/api/rahaza/master/bom/copy-missing', headers, all ? {} : { model_id: selectedModelId });
      toast.success(`${r.created} BOM dibuat untuk varian tanpa BOM${r.skipped?.length ? ` · ${r.skipped.length} dilewati (model belum punya BOM)` : ''}`);
      onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const recalc = async () => {
    setBusy('hpp');
    try {
      const r = await post('/api/rahaza/master/recalc-hpp', headers, {});
      toast.success(`HPP standar: ${r.panels_standard_costed} potongan dinilai · HPP ${r.models_hpp_applied} model diterapkan`);
      onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const addAccessories = async () => {
    if (!lines.length) return;
    setBusy('acc');
    try {
      const r = await post('/api/rahaza/master/bom/add-lines', headers, { model_id: selectedModelId, lines: lines.map((l) => ({ material_id: l.id, code: l.code, name: l.name, material_type: l.type, qty: Number(l.qty) || 1, unit: l.unit })) });
      toast.success(`${r.lines_appended} baris aksesoris ditambahkan ke ${r.boms_touched}/${r.boms_total} BOM ${modelLabel}`);
      setAccOpen(false); setLines([]); onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap" data-testid="bom-shortcuts">
      <Button size="sm" variant="outline" disabled={!selectedModelId || !!busy} onClick={() => copyMissing(false)} title="Buat BOM untuk semua varian model ini yang belum punya BOM — potongan & kain otomatis mengikuti warna/ukuran tujuan, aksesoris disalin" data-testid="bom-copy-missing-model">
        <Copy className="w-3.5 h-3.5 mr-1" />{busy === 'copy' ? 'Menyalin…' : 'Salin ke varian tanpa BOM'}
      </Button>
      <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => copyMissing(true)} className="text-xs" data-testid="bom-copy-missing-all">semua model</Button>
      <Button size="sm" variant="outline" disabled={!selectedModelId || !!busy} onClick={() => setAccOpen(true)} title="Tambah aksesoris yang sama ke SEMUA BOM aktif model ini" data-testid="bom-add-acc-bulk">
        <PackagePlus className="w-3.5 h-3.5 mr-1" />Aksesoris massal
      </Button>
      <Button size="sm" variant="outline" disabled={!!busy} onClick={recalc} title="Nilai potongan = qty kain × harga kain (standar, sampai cutting nyata), lalu HPP semua model diterapkan ke barang jadi & katalog" data-testid="bom-recalc-hpp">
        <Calculator className="w-3.5 h-3.5 mr-1" />{busy === 'hpp' ? 'Menghitung…' : 'Hitung HPP standar'}
      </Button>
      <Dialog open={accOpen} onOpenChange={setAccOpen}>
        <DialogContent className="max-w-2xl" data-testid="bom-acc-bulk-dialog">
          <DialogHeader><DialogTitle>Tambah aksesoris ke semua BOM · {modelLabel}</DialogTitle></DialogHeader>
          <p className="text-xs text-muted-foreground">Baris ditambahkan ke setiap BOM aktif model ini (semua warna & ukuran). Yang sudah ada dilewati.</p>
          <div className="space-y-2 max-h-[45vh] overflow-auto">
            {lines.map((l, i) => (
              <div key={l.id} className="flex items-center gap-2 text-sm" data-testid={`bom-acc-bulk-line-${l.code}`}>
                <span className="font-mono text-xs w-28 truncate">{l.code}</span><span className="flex-1 truncate">{l.name}</span>
                <GlassInput type="number" min="0" step="0.01" value={l.qty} onChange={(e) => setLines((xs) => xs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} className="h-8 w-24" data-testid={`bom-acc-bulk-qty-${l.code}`} />
                <span className="text-xs text-muted-foreground w-10">{l.unit}</span>
                <button onClick={() => setLines((xs) => xs.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-rose-400"><X className="w-4 h-4" /></button>
              </div>
            ))}
            <InlineMaterialPicker type="accessory" categories={categories} token={token} onSelect={(m) => setLines((xs) => (xs.some((x) => x.id === m.id) ? xs : [...xs, { id: m.id, code: m.code, name: m.name, type: m.type, unit: m.unit, qty: 1 }]))}>
              <Button size="sm" variant="outline" data-testid="bom-acc-bulk-pick"><PackagePlus className="w-3.5 h-3.5 mr-1" />Pilih aksesoris</Button>
            </InlineMaterialPicker>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAccOpen(false)}>Batal</Button>
            <Button onClick={addAccessories} disabled={!lines.length || busy === 'acc'} data-testid="bom-acc-bulk-save">{busy === 'acc' ? 'Menyimpan…' : `Tambahkan ${lines.length} baris`}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
