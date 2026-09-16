import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, Landmark, FileBarChart, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, authHeaders, downloadXlsx, YearSelect, MonthlyRow, MonthlyHead } from './reportShared';

const SECTIONS = ['assets', 'liabilities', 'equity'];

export default function RahazaBalanceSheetMonthlyModule({ token }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/balance-sheet-monthly?year=${year}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, year]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportXlsx = () => downloadXlsx(`/api/rahaza/finance/reports/export-xlsx?report=balance-sheet-monthly&year=${year}`, token, `neraca-12-bulan-${year}.xlsx`)
    .catch((e) => toast.error(`Ekspor gagal: ${e.message}`));

  const labels = data?.meta?.month_labels || [];
  const hasData = data && SECTIONS.some((s) => data.sections[s].accounts.length > 0);
  const last = (arr) => (arr && arr.length ? arr[arr.length - 1] : 0);

  return (
    <div className="space-y-5" data-testid="bs12-page">
      <PageHeader
        icon={Landmark}
        eyebrow="Portal Finance · Laporan"
        title="Neraca 12 Bulan"
        subtitle="Posisi keuangan per akhir tiap bulan Jan–Des seperti sheet Neraca-12. Setiap kolom harus seimbang: Aset = Liabilitas + Ekuitas (termasuk laba berjalan komputasi)."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" data-testid="bs12-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
            <Button variant="ghost" onClick={exportXlsx} disabled={!data} className="h-9 border border-[var(--glass-border)]" data-testid="bs12-export"><Download className="w-3.5 h-3.5 mr-1.5" />Ekspor Excel</Button>
          </>
        }
      />
      <GlassCard className="p-4 flex items-center gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground">Tahun</span>
        <YearSelect value={year} onChange={setYear} testId="bs12-year" />
        {data && (
          <span className={`inline-flex items-center gap-1 text-xs ${data.balanced ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="bs12-balanced">
            {data.balanced ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
            {data.balanced ? 'Semua kolom seimbang' : 'Ada kolom tidak seimbang — periksa jurnal tanpa akun neraca'}
          </span>
        )}
      </GlassCard>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label={`Total Aset Des ${year}`} value={fmt(last(data?.sections?.assets?.months))} testId="bs12-kpi-assets" />
        <StatTile label="Total Liabilitas" value={fmt(last(data?.sections?.liabilities?.months))} testId="bs12-kpi-liab" />
        <StatTile label="Total Ekuitas" value={fmt(last(data?.sections?.equity?.months))} testId="bs12-kpi-eq" />
        <StatTile label="Laba Berjalan" value={fmt(last(data?.totals?.current_earnings))} accent="primary" testId="bs12-kpi-earn" />
      </div>
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !hasData ? (
          <div className="py-16 text-center text-muted-foreground" data-testid="bs12-empty">
            <FileBarChart className="w-10 h-10 mx-auto mb-2 opacity-40" />Belum ada saldo neraca sampai akhir {year}. Mulai dari Master Akuntansi → Saldo Awal.
          </div>
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className="w-full text-sm" data-testid="bs12-table">
              <MonthlyHead labels={labels} year={year} />
              <tbody>
                {SECTIONS.map((s) => {
                  const sec = data.sections[s];
                  return [
                    <MonthlyRow key={`${s}-h`} code="" name={sec.label} months={sec.months.map(() => 0)} bold indent={false} />,
                    ...sec.accounts.map((a) => <MonthlyRow key={a.code} code={a.computed ? '' : a.code} name={a.name} months={a.months} tone={a.computed ? 'italic text-sky-300' : ''} testId={`bs12-row-${a.code}`} />),
                    <MonthlyRow key={`${s}-t`} code="" name={`Total ${sec.label}`} months={sec.months} bold testId={`bs12-total-${s}`} />,
                  ];
                })}
                <MonthlyRow code="" name="Total Liabilitas + Ekuitas" months={data.totals.liab_plus_equity} bold tone="text-sky-300" testId="bs12-liab-eq" />
                <MonthlyRow code="" name="Selisih (Aset − L&E)" months={data.totals.diff} tone={data.balanced ? 'text-muted-foreground' : 'text-rose-300'} indent={false} testId="bs12-diff" />
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
