import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, Columns3, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, fmtCell, authHeaders, downloadXlsx } from './reportShared';

const todayISO = () => new Date().toISOString().slice(0, 10);
const startOfYear = () => `${new Date().getFullYear()}-01-01`;
const COLS = ['opening_debit', 'opening_credit', 'period_debit', 'period_credit', 'end_debit', 'end_credit', 'pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'];
const HEAD = [['Saldo Awal', 2], ['Mutasi', 2], ['Saldo Akhir', 2], ['Laba Rugi', 2], ['Neraca', 2]];
const tdN = 'py-1.5 px-2 text-right font-mono text-xs whitespace-nowrap';

export default function RahazaWorksheetModule({ token }) {
  const [from, setFrom] = useState(startOfYear());
  const [to, setTo] = useState(todayISO());
  const [showZero, setShowZero] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ from, to, show_zero: showZero ? 'true' : 'false' });
      const r = await fetch(`/api/rahaza/finance/reports/worksheet?${q}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, from, to, showZero]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportXlsx = () => downloadXlsx(`/api/rahaza/finance/reports/export-xlsx?report=worksheet&from=${from}&to=${to}&show_zero=${showZero}`, token, `neraca-lajur-${from}-${to}.xlsx`)
    .catch((e) => toast.error(`Ekspor gagal: ${e.message}`));

  const t = data?.totals || {};
  const b = data?.balancing || {};
  const g = data?.grand_totals || {};

  return (
    <div className="space-y-5" data-testid="worksheet-page">
      <PageHeader
        icon={Columns3}
        eyebrow="Portal Finance · Laporan"
        title="Neraca Lajur"
        subtitle="Kertas kerja 10 kolom seperti sheet N-Lajur: saldo awal · mutasi · saldo akhir, lalu tiap akun dipisah ke kolom Laba Rugi atau Neraca. Baris laba/rugi bersih menyeimbangkan kedua pasangan kolom."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" data-testid="ws-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
            <Button variant="ghost" onClick={exportXlsx} disabled={!data} className="h-9 border border-[var(--glass-border)]" data-testid="ws-export"><Download className="w-3.5 h-3.5 mr-1.5" />Ekspor Excel</Button>
          </>
        }
      />
      <GlassCard className="p-4">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-muted-foreground">Dari</span>
          <GlassInput type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 w-36" data-testid="ws-from" />
          <span className="text-xs text-muted-foreground">s/d</span>
          <GlassInput type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 w-36" data-testid="ws-to" />
          <label className="inline-flex items-center gap-2 text-xs text-foreground/80">
            <input type="checkbox" checked={showZero} onChange={(e) => setShowZero(e.target.checked)} data-testid="ws-show-zero" />
            Tampilkan akun saldo 0
          </label>
          {data && (
            <span className={`inline-flex items-center gap-1 text-xs ${data.balanced ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="ws-balanced">
              {data.balanced ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
              {data.balanced ? 'Seimbang' : 'TIDAK seimbang'}
            </span>
          )}
        </div>
      </GlassCard>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Mutasi Debit" value={fmt(t.period_debit)} testId="ws-kpi-pd" />
        <StatTile label="Mutasi Kredit" value={fmt(t.period_credit)} testId="ws-kpi-pc" />
        <StatTile label={b.label || 'Laba Bersih'} value={fmt(b.net_income)} accent={(b.net_income || 0) >= 0 ? 'success' : 'danger'} testId="ws-kpi-net" />
        <StatTile label="Total Neraca (D = K)" value={fmt(g.bs_debit)} accent="primary" testId="ws-kpi-bs" />
      </div>
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !data?.rows?.length ? (
          <div className="py-16 text-center text-muted-foreground" data-testid="ws-empty">
            <FileBarChart className="w-10 h-10 mx-auto mb-2 opacity-40" />Tidak ada data pada periode ini.
          </div>
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className="w-full text-sm" data-testid="ws-table">
              <thead className="sticky top-0 z-10 bg-[var(--card-surface)] backdrop-blur-sm text-[10px] uppercase text-muted-foreground">
                <tr className="border-b border-[var(--glass-border)]">
                  <th rowSpan={2} className="py-2 px-2 text-left">Kode</th>
                  <th rowSpan={2} className="py-2 px-2 text-left">Akun</th>
                  {HEAD.map(([l, span]) => <th key={l} colSpan={span} className="py-1 px-2 text-center border-l border-[var(--glass-border)]">{l}</th>)}
                </tr>
                <tr className="border-b border-[var(--glass-border)]">
                  {HEAD.map(([l]) => [<th key={`${l}-d`} className="py-1 px-2 text-right border-l border-[var(--glass-border)]">Debit</th>, <th key={`${l}-k`} className="py-1 px-2 text-right">Kredit</th>])}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.code} className="border-b border-[var(--glass-border)] hover:bg-foreground/5" data-testid={`ws-row-${r.code}`}>
                    <td className="py-1.5 px-2 font-mono text-xs">{r.code}</td>
                    <td className="py-1.5 px-2 text-xs whitespace-nowrap">{r.name} <span className="text-[9px] uppercase text-muted-foreground ml-1">{r.statement === 'pl' ? 'L/R' : 'NRC'}</span></td>
                    {COLS.map((c, i) => <td key={c} className={`${tdN} ${i % 2 === 0 ? 'border-l border-[var(--glass-border)]' : ''} ${c.startsWith('pl') ? 'text-amber-200' : c.startsWith('bs') ? 'text-sky-200' : ''}`}>{fmtCell(r[c])}</td>)}
                  </tr>
                ))}
                <tr className="font-semibold bg-[var(--card-surface)] border-t-2 border-[var(--glass-border)]" data-testid="ws-totals">
                  <td colSpan={2} className="py-2 px-2 text-right text-xs uppercase">Jumlah</td>
                  {COLS.map((c) => <td key={c} className={tdN}>{fmt(t[c])}</td>)}
                </tr>
                <tr className="bg-[var(--card-surface)]" data-testid="ws-balancing">
                  <td colSpan={2} className={`py-2 px-2 text-right text-xs uppercase ${b.net_income >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{b.label}</td>
                  {COLS.slice(0, 6).map((c) => <td key={c} className={tdN} />)}
                  {['pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'].map((c) => <td key={c} className={`${tdN} font-semibold`}>{fmtCell(b[c])}</td>)}
                </tr>
                <tr className="font-bold bg-[var(--card-surface)] border-t-2 border-[var(--glass-border)]" data-testid="ws-grand">
                  <td colSpan={2} className="py-2 px-2 text-right text-xs uppercase">Total</td>
                  {COLS.slice(0, 6).map((c) => <td key={c} className={tdN} />)}
                  {['pl_debit', 'pl_credit', 'bs_debit', 'bs_credit'].map((c) => <td key={c} className={tdN}>{fmt(g[c])}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
