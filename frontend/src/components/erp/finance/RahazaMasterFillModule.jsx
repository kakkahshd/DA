import { useState, useRef, useEffect, useCallback } from 'react';
import { Download, Upload, CheckCircle2, AlertTriangle, FileSpreadsheet } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'py-1.5 px-2 text-right font-mono text-xs';

export default function RahazaMasterFillModule({ token }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  const doPreview = useCallback(async () => {
    if (!file) { setPreview(null); return; }
    setBusy(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch('/api/rahaza/master/fill-preview', { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : 'Gagal membaca berkas'); return; }
      setPreview(j); setResult(null);
    } finally { setBusy(false); }
  }, [file, token]);
  useEffect(() => { doPreview(); }, [doPreview]);

  const doApply = async () => {
    setBusy(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch('/api/rahaza/master/fill-apply', { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : j.detail?.message || 'Gagal'); return; }
      setResult(j); setFile(null); setPreview(null); if (inputRef.current) inputRef.current.value = '';
      toast.success(`Diterapkan: ${j.materials_updated} material · ${j.accounts_updated} rekening · ${j.stores_updated} toko · HPP ${j.models_hpp_applied} model`);
    } finally { setBusy(false); }
  };
  const dl = () => downloadXlsx('/api/rahaza/master/fill-template', token, 'TEMPLATE_HARGA_SATUAN_REKENING_BOM.xlsx').catch((e) => toast.error(e.message));
  const t = preview?.totals || {};

  return (
    <div className="space-y-5" data-testid="fill-page">
      <PageHeader icon={FileSpreadsheet} eyebrow="Master · Pengisian Massal" title="Impor Harga · Satuan · Rekening · BOM"
        subtitle="Satu template untuk data yang hanya Anda yang tahu: harga & isi per satuan beli tiap material (sistem menghitung harga per satuan dasar dan menyimpan konversinya), nomor rekening & atas nama bank, rekening pencairan tiap toko, aksesoris/bahan BOM per model (sheet BOM_AKSESORIS), dan berat model (sheet MODEL). Setelah diterapkan, biaya standar potongan dan HPP semua model dihitung ulang otomatis." />
      <div className="grid md:grid-cols-3 gap-4">
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 1</div><h3 className="font-semibold text-sm">Unduh template</h3>
          <p className="text-xs text-muted-foreground">Sheet MATERIAL (kain & aksesoris), REKENING, TOKO, BOM_AKSESORIS (satu baris per bahan per model — model tanpa aksesoris sudah ditandai), MODEL (berat gram).</p>
          <Button onClick={dl} className="h-9 w-full" data-testid="fill-download"><Download className="w-3.5 h-3.5 mr-1.5" />Template Excel</Button></GlassCard>
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 2</div><h3 className="font-semibold text-sm">Unggah berkas terisi</h3>
          <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/20 file:px-3 file:py-1.5 file:text-xs file:text-primary" data-testid="fill-file" />
          <p className="text-xs text-muted-foreground">Pratinjau muncul otomatis; baris kosong tidak diubah.</p></GlassCard>
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 3</div><h3 className="font-semibold text-sm">Terapkan</h3>
          <Button onClick={doApply} disabled={!preview?.ok || busy || !(t.materials + t.accounts + t.stores + (t.bom_lines || 0) + (t.models || 0))} className="h-9 w-full" data-testid="fill-apply">
            {preview?.ok ? <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" /> : <Upload className="w-3.5 h-3.5 mr-1.5" />}Terapkan & Hitung HPP</Button></GlassCard>
      </div>
      {preview && (
        <div className="space-y-3" data-testid="fill-preview">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <StatTile label="Material berubah" value={t.materials} testId="fill-kpi-mat" />
            <StatTile label="Rekening" value={t.accounts} testId="fill-kpi-acc" />
            <StatTile label="Toko" value={t.stores} testId="fill-kpi-store" />
            <StatTile label="Baris BOM" value={`${t.bom_lines || 0} (${t.bom_models || 0} model)`} testId="fill-kpi-bom" />
            <StatTile label="Berat model" value={t.models || 0} testId="fill-kpi-model" />
            <StatTile label={preview.ok ? 'Siap' : `${preview.errors.length} masalah`} value={preview.ok ? '✓' : '✗'} accent={preview.ok ? 'success' : 'danger'} testId="fill-kpi-status" />
          </div>
          {preview.errors.length > 0 && <GlassCard className="p-4 border border-rose-500/30 text-xs" data-testid="fill-errors"><div className="inline-flex items-center gap-2 text-rose-300 font-semibold mb-2"><AlertTriangle className="w-4 h-4" />Perbaiki dulu</div><ul className="list-disc pl-5 space-y-1">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></GlassCard>}
          {preview.materials.length > 0 && (
            <GlassCard className="p-0 overflow-hidden"><div className="overflow-auto max-h-[40vh]"><table className="w-full text-sm" data-testid="fill-mat-table">
              <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground"><tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Kode</th><th className="py-2 px-2 text-left">Nama</th><th className="py-2 px-2 text-left">Beli</th><th className="py-2 px-2 text-right">Isi</th><th className="py-2 px-2 text-right">Harga beli</th><th className="py-2 px-2 text-right">→ per {'{dasar}'}</th><th className="py-2 px-2 text-right">Sebelumnya</th></tr></thead>
              <tbody>{preview.materials.map((m) => <tr key={m.code} className="border-b border-[var(--glass-border)]" data-testid={`fill-mat-${m.code}`}><td className="py-1.5 px-2 font-mono text-xs">{m.code}</td><td className="py-1.5 px-2 text-xs">{m.name}</td><td className="py-1.5 px-2 text-xs">{m.buy_unit}</td><td className={tdN}>{m.pack_size} {m.base_unit}</td><td className={tdN}>{m.buy_price ? fmt(m.buy_price) : ''}</td><td className={`${tdN} text-emerald-300`}>{m.unit_cost != null ? `${fmt(m.unit_cost)}/${m.base_unit}` : ''}</td><td className={`${tdN} text-muted-foreground`}>{fmt(m.unit_cost_before)}</td></tr>)}</tbody>
            </table></div></GlassCard>
          )}
          {(preview.bom_lines || []).length > 0 && (
            <GlassCard className="p-0 overflow-hidden" data-testid="fill-bom-table"><div className="overflow-auto max-h-[40vh]"><table className="w-full text-sm">
              <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground"><tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Model</th><th className="py-2 px-2 text-left">Material</th><th className="py-2 px-2 text-right">Qty/pcs</th><th className="py-2 px-2 text-left">Satuan</th></tr></thead>
              <tbody>{preview.bom_lines.map((b, i) => <tr key={i} className="border-b border-[var(--glass-border)]"><td className="py-1.5 px-2 font-mono text-xs">{b.model_code}</td><td className="py-1.5 px-2 text-xs"><span className="font-mono">{b.code}</span> {b.name}</td><td className={tdN}>{b.qty}</td><td className="py-1.5 px-2 text-xs">{b.unit}</td></tr>)}</tbody>
            </table></div></GlassCard>
          )}
          {(preview.models || []).length > 0 && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-models">{preview.models.map((m) => <div key={m.model_code}>Model <span className="font-mono">{m.model_code}</span> → berat {m.weight_gram} gram</div>)}</GlassCard>
          )}
          {(preview.accounts.length > 0 || preview.stores.length > 0) && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-acc-store">
              {preview.accounts.map((a) => <div key={a.gl_account_code}><span className="font-mono">{a.gl_account_code}</span> → no. rek {a.account_number || '-'} a.n. {a.holder_name || '-'}</div>)}
              {preview.stores.map((s) => <div key={s.account_code}>Toko <span className="font-mono">{s.account_code}</span> → pencairan ke <span className="font-mono">{s.coa_cash_code}</span></div>)}
            </GlassCard>
          )}
        </div>
      )}
      {result && <GlassCard className="p-4 text-xs text-emerald-300" data-testid="fill-result">Selesai: {result.materials_updated} material · {result.accounts_updated} rekening · {result.stores_updated} toko · BOM: {result.bom_lines_appended || 0} baris ke {result.boms_touched || 0} BOM, {result.bom_base_created || 0} BOM dasar baru · {result.models_weight_updated || 0} berat model · {result.panels_standard_costed} potongan dinilai standar · HPP {result.models_hpp_applied} model diterapkan{result.units_added?.length ? ` · satuan baru: ${result.units_added.join(', ')}` : ''}</GlassCard>}
    </div>
  );
}
