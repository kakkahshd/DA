import { useEffect, useState } from 'react';
import { FileSpreadsheet, Download, RefreshCw } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { apiGet, apiFetch } from '../../../lib/api';

const fmt = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
const GROUPS = [['customer', 'Per Pelanggan'], ['sku', 'Per SKU'], ['day', 'Per Hari'], ['month', 'Per Bulan']];
const firstOfMonth = () => new Date().toISOString().slice(0, 8) + '01';
const today = () => new Date().toISOString().slice(0, 10);

export default function SalesReportModule() {
  const [group, setGroup] = useState('customer');
  const [from, setFrom] = useState(firstOfMonth());
  const [to, setTo] = useState(today());
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const qs = `group_by=${group}&date_from=${from}&date_to=${to}`;
  const load = async () => { setBusy(true); try { setD(await apiGet(`/sales/report?${qs}`)); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };
  useEffect(() => { load(); }, [group, from, to]); // eslint-disable-line react-hooks/exhaustive-deps
  const exportCsv = async () => {
    const r = await apiFetch(`/sales/report?${qs}&format=csv`);
    if (!r.ok) return toast.error('Gagal export CSV');
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a'); a.href = url; a.download = `laporan_penjualan_${group}_${from}_${to}.csv`; a.click();
  };
  const t = d?.totals;
  const head = { customer: 'Pelanggan', sku: 'SKU', day: 'Tanggal', month: 'Bulan' }[group];

  return (
    <div className="space-y-5" data-testid="sales-report">
      <PageHeader icon={FileSpreadsheet} eyebrow="Portal Penjualan" title="Laporan Penjualan Langsung" subtitle="Penjualan bersih = bruto − diskon − retur (tanpa PPN). HPP dari lapisan FIFO / perkiraan HPP master, sudah dikurangi HPP barang retur."
        actions={<>
          <Button variant="ghost" onClick={load} className="h-9 border border-[var(--glass-border)]" data-testid="report-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
          <Button onClick={exportCsv} className="h-9" data-testid="report-export-csv"><Download className="w-3.5 h-3.5 mr-1.5" />Export CSV</Button>
        </>} />
      <GlassCard className="p-3 flex flex-wrap items-center gap-3 text-xs">
        <div className="flex gap-1" data-testid="report-group-tabs">{GROUPS.map(([v, l]) => (
          <button key={v} onClick={() => setGroup(v)} data-testid={`report-group-${v}`} className={`px-3 py-1.5 rounded-md border transition-colors ${group === v ? 'bg-primary text-primary-foreground border-primary' : 'border-[var(--glass-border)] hover:bg-foreground/5'}`}>{l}</button>
        ))}</div>
        <label className="flex items-center gap-1.5 ml-auto">Dari <GlassInput type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-8 w-36" data-testid="report-from" /></label>
        <label className="flex items-center gap-1.5">Sampai <GlassInput type="date" value={to} onChange={e => setTo(e.target.value)} className="h-8 w-36" data-testid="report-to" /></label>
      </GlassCard>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile label="Nota" value={t?.notes ?? '-'} hint={`${t?.qty || 0} pcs · retur ${t?.return_qty || 0} pcs`} testId="report-kpi-notes" />
        <StatTile label="Penjualan Bersih" value={fmt(t?.net_sales)} hint={`bruto ${fmt(t?.gross)}`} accent="primary" testId="report-kpi-net" />
        <StatTile label="Diskon + Retur" value={fmt((t?.discount || 0) + (t?.returns || 0))} hint={`PPN ${fmt(t?.tax)}`} testId="report-kpi-deductions" />
        <StatTile label="HPP" value={fmt(t?.cogs)} testId="report-kpi-cogs" />
        <StatTile label="Laba Kotor" value={fmt(t?.margin)} hint={`${t?.margin_pct || 0}% margin`} accent={(t?.margin || 0) >= 0 ? 'success' : 'danger'} testId="report-kpi-margin" />
      </div>
      <GlassCard className="p-0 overflow-x-auto">
        {busy && !d ? <div className="py-10 text-center text-sm text-muted-foreground">Memuat…</div> : !d?.rows?.length ? <div className="py-14 text-center text-sm text-muted-foreground" data-testid="report-empty">Tidak ada penjualan pada rentang ini.</div> : (
          <table className="w-full text-xs" data-testid="report-table">
            <thead className="bg-foreground/5 text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">{head}</th><th className="text-right px-3 py-2">Nota</th><th className="text-right px-3 py-2">Qty</th><th className="text-right px-3 py-2">Bruto</th><th className="text-right px-3 py-2">Diskon</th><th className="text-right px-3 py-2">Retur</th><th className="text-right px-3 py-2">Bersih</th><th className="text-right px-3 py-2">HPP</th><th className="text-right px-3 py-2">Laba Kotor</th><th className="text-right px-3 py-2">Margin</th>
            </tr></thead>
            <tbody>{d.rows.map(r => (
              <tr key={r.key} className="border-t border-foreground/5" data-testid={`report-row-${r.key}`}>
                <td className="px-3 py-2 font-medium">{r.label}</td><td className="px-3 py-2 text-right">{r.notes}</td><td className="px-3 py-2 text-right">{r.qty}{r.return_qty ? <span className="text-amber-300"> (−{r.return_qty})</span> : ''}</td>
                <td className="px-3 py-2 text-right">{fmt(r.gross)}</td><td className="px-3 py-2 text-right">{fmt(r.discount)}</td><td className="px-3 py-2 text-right">{fmt(r.returns)}</td>
                <td className="px-3 py-2 text-right font-semibold">{fmt(r.net_sales)}</td><td className="px-3 py-2 text-right">{fmt(r.cogs)}</td><td className="px-3 py-2 text-right font-semibold">{fmt(r.margin)}</td><td className="px-3 py-2 text-right">{r.margin_pct}%</td>
              </tr>
            ))}</tbody>
            <tfoot><tr className="border-t border-foreground/10 font-semibold bg-foreground/5" data-testid="report-total-row">
              <td className="px-3 py-2">TOTAL</td><td className="px-3 py-2 text-right">{t.notes}</td><td className="px-3 py-2 text-right">{t.qty}</td><td className="px-3 py-2 text-right">{fmt(t.gross)}</td><td className="px-3 py-2 text-right">{fmt(t.discount)}</td><td className="px-3 py-2 text-right">{fmt(t.returns)}</td><td className="px-3 py-2 text-right">{fmt(t.net_sales)}</td><td className="px-3 py-2 text-right">{fmt(t.cogs)}</td><td className="px-3 py-2 text-right">{fmt(t.margin)}</td><td className="px-3 py-2 text-right">{t.margin_pct}%</td>
            </tr></tfoot>
          </table>
        )}
      </GlassCard>
    </div>
  );
}
