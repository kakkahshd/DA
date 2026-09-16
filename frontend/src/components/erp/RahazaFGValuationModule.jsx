import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Boxes, Download, BookCheck } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import CronJobCard from './CronJobCard';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
const todayISO = () => new Date().toISOString().slice(0, 10);

export default function RahazaFGValuationModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [asOf, setAsOf] = useState(todayISO());
  const [backfill, setBackfill] = useState(null);
  const [busy, setBusy] = useState(false);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/fg-inventory-valuation?as_of=${asOf}`, { headers });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, asOf]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const runBackfill = async (dryRun) => {
    if (!dryRun && !window.confirm('Posting jurnal WIP→Barang Jadi untuk semua Terima FG dari CMT (PO internal) yang belum berjurnal?')) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/prod/cmt-receipts/backfill-wip-fg?dry_run=${dryRun}`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) { alert(d.detail || 'Error'); return; }
      setBackfill(d);
      if (!dryRun) fetchData();
    } finally { setBusy(false); }
  };

  const exportCSV = () => {
    if (!data?.rows) return;
    const csv = [
      ['Kode', 'Nama', 'Stok Fisik', 'Qty Lapisan', 'Selisih Qty', 'HPP Rata-rata', 'Nilai Lapisan', 'Belum Berjurnal', 'Qty Tanpa Biaya'],
      ...data.rows.map(r => [r.code, r.name, r.stock_qty, r.layer_qty, r.qty_diff, r.avg_unit_cost, r.layer_value, r.unposted_value, r.uncosted_qty]),
    ].map(r => r.map(c => typeof c === 'string' && c.includes(',') ? `"${c}"` : c).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `nilai-persediaan-fg-${asOf}.csv`; a.click(); URL.revokeObjectURL(url);
  };

  const t = data?.totals || {};
  return (
    <div className="space-y-5" data-testid="rahaza-fgval-page">
      <PageHeader
        icon={Boxes}
        eyebrow="Portal Finance · Laporan"
        title="Nilai Persediaan Barang Jadi (Lapisan FIFO vs GL 1-1404)"
        subtitle="Kartu stok FG dari lapisan HPP batch dibandingkan saldo akun Persediaan Barang Jadi. Selisih dijelaskan: lapisan belum berjurnal & lapisan tanpa biaya."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" data-testid="fgval-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
            <Button variant="ghost" onClick={exportCSV} className="h-9 border border-[var(--glass-border)]" disabled={!data?.rows?.length} data-testid="fgval-export"><Download className="w-3.5 h-3.5 mr-1.5" />Export CSV</Button>
          </>
        }
      />

      <GlassCard className="p-4 flex items-center gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground">Saldo GL per</span>
        <GlassInput type="date" value={asOf} onChange={e => setAsOf(e.target.value)} className="h-8 w-36" data-testid="fgval-asof" />
        <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded border ${data?.reconciled ? 'text-emerald-300 bg-emerald-400/10 border-emerald-400/25' : data?.explained ? 'text-amber-300 bg-amber-400/10 border-amber-400/25' : 'text-red-300 bg-red-400/10 border-red-400/25'}`} data-testid="fgval-status">
          {data?.reconciled ? 'Cocok dengan GL' : data?.explained ? 'Selisih terjelaskan (lapisan belum berjurnal)' : 'Selisih belum terjelaskan'}
        </span>
      </GlassCard>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Nilai Lapisan FIFO" value={`Rp ${fmt(t.layer_value)}`} accent="primary" testId="fgval-kpi-layer" />
        <StatTile label={`Saldo GL 1-1404 (${data?.as_of || asOf})`} value={`Rp ${fmt(t.gl_balance)}`} testId="fgval-kpi-gl" />
        <StatTile label="Selisih (Lapisan − GL)" value={`Rp ${fmt(t.difference)}`} accent={Math.abs(t.difference || 0) < 1 ? 'success' : 'danger'} testId="fgval-kpi-diff" />
        <StatTile label="Belum Berjurnal (WIP→FG)" value={`Rp ${fmt(t.unposted_value)} · ${t.unposted_layers || 0} lapisan`} accent={t.unposted_layers ? 'danger' : 'success'} testId="fgval-kpi-unposted" />
      </div>

      {(t.unposted_layers > 0 || backfill) && (
        <GlassCard className="p-4" data-testid="fgval-backfill-card">
          <div className="flex flex-wrap items-center gap-3">
            <BookCheck className="w-4 h-4 text-amber-300" />
            <div className="text-sm">
              <span className="font-semibold">Backfill WIP→FG:</span> Terima FG dari CMT (PO internal) yang sudah selesai QC tetapi belum punya jurnal Dr 1-1404 / Cr 1-1403.
            </div>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => runBackfill(true)} data-testid="fgval-backfill-preview">Lihat kandidat</Button>
              <Button size="sm" disabled={busy || !(backfill?.candidates > 0) || !backfill?.dry_run} onClick={() => runBackfill(false)} data-testid="fgval-backfill-run">Posting sekarang</Button>
            </div>
          </div>
          {backfill && (
            <div className="mt-3 text-xs text-foreground/70" data-testid="fgval-backfill-result">
              {backfill.dry_run ? `${backfill.candidates} kandidat · Rp ${fmt(backfill.total_value)}` : `${backfill.posted} jurnal diposting · Rp ${fmt(backfill.total_value)}`}
              {backfill.rows?.slice(0, 10).map(r => (
                <div key={r.receipt_id} className="font-mono">{r.receipt_code} · {r.po_number} · {r.layers} lapisan · Rp {fmt(r.value)} → {r.result}{r.je_number ? ` (${r.je_number})` : ''}{r.error ? ` — ${r.error}` : ''}</div>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      <CronJobCard job="fg-valuation-check" title="Rekonsiliasi otomatis" description="setiap hari 07:00 WIB; Finance diberi notifikasi bila selisih belum terjelaskan"
        renderResult={(r) => `selisih Rp ${fmt(r.difference)} · belum terjelaskan Rp ${fmt(r.unexplained_difference)}${r.notified ? ' · notifikasi terkirim' : ''}`} onRan={fetchData} />

      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !data?.rows?.length ? (
          <div className="py-16 text-center text-muted-foreground text-sm" data-testid="fgval-empty">Belum ada lapisan HPP / stok FG internal.</div>
        ) : (
          <table className="w-full text-xs" data-testid="fgval-table">
            <thead className="bg-foreground/5 text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">SKU</th>
                <th className="text-right px-3 py-2">Stok Fisik</th>
                <th className="text-right px-3 py-2">Qty Lapisan</th>
                <th className="text-right px-3 py-2">Selisih Qty</th>
                <th className="text-right px-3 py-2">HPP Rata-rata</th>
                <th className="text-right px-3 py-2">Nilai Lapisan</th>
                <th className="text-right px-3 py-2">Belum Berjurnal</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map(r => (
                <tr key={r.material_id} className="border-t border-foreground/5" data-testid={`fgval-row-${r.code}`}>
                  <td className="px-3 py-2"><div className="font-mono">{r.code}</div><div className="text-muted-foreground">{r.name}</div></td>
                  <td className="px-3 py-2 text-right">{fmt(r.stock_qty)}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.layer_qty)}{r.uncosted_qty > 0 && <div className="text-[10px] text-amber-300">{fmt(r.uncosted_qty)} tanpa biaya</div>}</td>
                  <td className={`px-3 py-2 text-right ${r.qty_diff ? 'text-amber-300' : ''}`}>{fmt(r.qty_diff)}</td>
                  <td className="px-3 py-2 text-right">Rp {fmt(r.avg_unit_cost)}</td>
                  <td className="px-3 py-2 text-right font-semibold">Rp {fmt(r.layer_value)}</td>
                  <td className={`px-3 py-2 text-right ${r.unposted_value ? 'text-red-300' : 'text-muted-foreground'}`}>Rp {fmt(r.unposted_value)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-foreground/5 font-semibold">
              <tr>
                <td className="px-3 py-2">Total</td>
                <td className="px-3 py-2 text-right">{fmt(t.stock_qty)}</td>
                <td className="px-3 py-2 text-right">{fmt(t.layer_qty)}</td>
                <td className="px-3 py-2 text-right">{fmt((t.stock_qty || 0) - (t.layer_qty || 0))}</td>
                <td className="px-3 py-2" />
                <td className="px-3 py-2 text-right">Rp {fmt(t.layer_value)}</td>
                <td className="px-3 py-2 text-right">Rp {fmt(t.unposted_value)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </GlassCard>
    </div>
  );
}
