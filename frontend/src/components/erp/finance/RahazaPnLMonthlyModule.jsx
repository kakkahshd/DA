import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Download, CalendarRange, FileBarChart } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, authHeaders, downloadXlsx, YearSelect, MonthlyRow, MonthlyHead } from './reportShared';

const GROUPS = ['revenue', 'cogs', 'expense', 'other_income', 'other_expense'];

export default function RahazaPnLMonthlyModule({ token }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/finance/reports/profit-loss-monthly?year=${year}`, { headers: authHeaders(token) });
      if (r.ok) setData(await r.json()); else toast.error(`Gagal memuat (HTTP ${r.status})`);
    } finally { setLoading(false); }
  }, [token, year]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const exportXlsx = () => downloadXlsx(`/api/rahaza/finance/reports/export-xlsx?report=profit-loss-monthly&year=${year}`, token, `laba-rugi-12-bulan-${year}.xlsx`)
    .catch((e) => toast.error(`Ekspor gagal: ${e.message}`));

  const L = data?.lines || {};
  const labels = data?.meta?.month_labels || [];
  const hasData = data && GROUPS.some((g) => data.groups[g].accounts.length > 0);

  return (
    <div className="space-y-5" data-testid="pnl12-page">
      <PageHeader
        icon={CalendarRange}
        eyebrow="Portal Finance · Laporan"
        title="Laba Rugi 12 Bulan"
        subtitle="Satu tabel Jan–Des seperti sheet Laba-12: pendapatan, HPP, beban, laba bersih per bulan, total tahun, dan akumulasi s/d bulan. Angka dari buku besar (jurnal posted), jurnal penutup tidak ikut."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" data-testid="pnl12-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
            <Button variant="ghost" onClick={exportXlsx} disabled={!data} className="h-9 border border-[var(--glass-border)]" data-testid="pnl12-export"><Download className="w-3.5 h-3.5 mr-1.5" />Ekspor Excel</Button>
          </>
        }
      />
      <GlassCard className="p-4 flex items-center gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground">Tahun</span>
        <YearSelect value={year} onChange={setYear} testId="pnl12-year" />
      </GlassCard>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label={`Pendapatan ${year}`} value={fmt(data?.groups?.revenue?.total)} testId="pnl12-kpi-rev" />
        <StatTile label="Laba Kotor" value={fmt(L.gross_profit?.total)} testId="pnl12-kpi-gross" />
        <StatTile label="Beban Operasional" value={fmt(data?.groups?.expense?.total)} testId="pnl12-kpi-exp" />
        <StatTile label="Laba Bersih" value={fmt(L.net_income?.total)} accent={(L.net_income?.total || 0) >= 0 ? 'success' : 'danger'} testId="pnl12-kpi-net" />
      </div>
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !hasData ? (
          <div className="py-16 text-center text-muted-foreground" data-testid="pnl12-empty">
            <FileBarChart className="w-10 h-10 mx-auto mb-2 opacity-40" />Belum ada jurnal laba rugi di tahun {year}.
          </div>
        ) : (
          <div className="overflow-auto max-h-[70vh]">
            <table className="w-full text-sm" data-testid="pnl12-table">
              <MonthlyHead labels={labels} year={year} withTotal />
              <tbody>
                {GROUPS.map((g) => {
                  const grp = data.groups[g];
                  return [
                    <MonthlyRow key={`${g}-h`} code="" name={grp.label} months={grp.months.map(() => 0)} total={undefined} bold indent={false} />,
                    ...grp.accounts.map((a) => <MonthlyRow key={a.code} code={a.code} name={a.name} months={a.months} total={a.total} testId={`pnl12-row-${a.code}`} />),
                    <MonthlyRow key={`${g}-t`} code="" name={`Total ${grp.label}`} months={grp.months} total={grp.total} bold testId={`pnl12-total-${g}`} />,
                    g === 'cogs' && <MonthlyRow key="gross" code="" name="Laba Kotor" months={L.gross_profit.months} total={L.gross_profit.total} bold tone="text-sky-300" testId="pnl12-gross" />,
                    g === 'expense' && <MonthlyRow key="op" code="" name="Laba Operasi" months={L.operating_income.months} total={L.operating_income.total} bold tone="text-sky-300" testId="pnl12-operating" />,
                  ];
                })}
                <MonthlyRow code="" name="Laba Bersih" months={L.net_income.months} total={L.net_income.total} bold tone={L.net_income.total >= 0 ? 'text-emerald-300' : 'text-rose-300'} testId="pnl12-net" />
                <MonthlyRow code="" name="Akumulasi s/d bulan" months={L.net_income_cumulative.months} total={L.net_income_cumulative.total} tone="text-muted-foreground" indent={false} testId="pnl12-cum" />
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
