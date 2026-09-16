import { useEffect, useState } from 'react';
import { LineChart, RefreshCw, ReceiptText, Wallet, AlertTriangle, TrendingUp } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from '../moduleAtoms';
import OnwardCTA from '../OnwardCTA';
import { apiGet } from '../../../lib/api';

const fmt = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;

export default function SalesDashboardModule({ onNavigate }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = async () => {
    try { setErr(''); setD(await apiGet('/sales/dashboard')); } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-5" data-testid="sales-dashboard">
      <PageHeader icon={LineChart} eyebrow="Portal Penjualan" title="Dashboard Penjualan Langsung"
        subtitle="Penjualan dari stok barang jadi sendiri. Setiap nota terkonfirmasi mengurangi stok FG (FIFO), membukukan HPP, dan menerbitkan invoice ke Keuangan."
        actions={<Button variant="ghost" onClick={load} className="h-9 border border-[var(--glass-border)]" data-testid="sales-dash-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>} />
      {err && <div className="text-sm text-red-400" data-testid="sales-dash-error">{err}</div>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Penjualan Hari Ini" value={fmt(d?.today_sales)} hint={`${d?.today_count || 0} nota`} accent="primary" testId="sales-kpi-today" />
        <StatTile label="Penjualan Bulan Ini" value={fmt(d?.month_sales)} hint={`${d?.month_count || 0} nota · HPP ${fmt(d?.month_cogs)}`} testId="sales-kpi-month" />
        <StatTile label="Laba Kotor Bulan Ini" value={fmt(d?.month_gross_margin)} accent={(d?.month_gross_margin || 0) >= 0 ? 'success' : 'danger'} testId="sales-kpi-margin" />
        <StatTile label="Piutang Belum Lunas" value={fmt(d?.open_ar)} hint={`${d?.open_ar_count || 0} invoice · overdue ${fmt(d?.overdue_ar)}`} accent={d?.overdue_count ? 'danger' : 'default'} testId="sales-kpi-ar" />
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <GlassCard className="p-4">
          <div className="flex items-center gap-2 mb-3 text-sm font-semibold"><TrendingUp className="w-4 h-4" />SKU Terlaris Bulan Ini</div>
          {!d?.top_skus?.length ? <div className="text-xs text-muted-foreground" data-testid="sales-top-empty">Belum ada penjualan bulan ini.</div> : (
            <table className="w-full text-xs" data-testid="sales-top-table">
              <thead className="text-muted-foreground"><tr><th className="text-left py-1">SKU</th><th className="text-right">Qty</th><th className="text-right">Nilai</th></tr></thead>
              <tbody>{d.top_skus.map(s => (
                <tr key={s.sku} className="border-t border-foreground/5"><td className="py-1.5"><div className="font-mono">{s.sku}</div><div className="text-muted-foreground">{s.name}</div></td><td className="text-right">{s.qty}</td><td className="text-right font-semibold">{fmt(s.amount)}</td></tr>
              ))}</tbody>
            </table>
          )}
        </GlassCard>
        <GlassCard className="p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold"><ReceiptText className="w-4 h-4" />Status Nota</div>
          <div className="text-xs text-muted-foreground flex items-center gap-2"><AlertTriangle className="w-3.5 h-3.5 text-amber-400" />{d?.draft_count || 0} nota masih draft (belum mengurangi stok).</div>
          <div className="text-xs text-muted-foreground flex items-center gap-2"><Wallet className="w-3.5 h-3.5 text-emerald-400" />Alur akuntansi: Dr Piutang/Kas · Cr Penjualan (+PPN) dan Dr HPP · Cr Persediaan FG 1-1404 (FIFO).</div>
          <OnwardCTA onNavigate={onNavigate} title="Langkah Berikutnya" actions={[
            { module: 'sales-direct', label: 'Buat Nota Penjualan', icon: ReceiptText, primary: true },
            { module: 'sales-customers', label: 'Master Pelanggan' },
            { module: 'fin-ar-360', label: 'Aging Piutang (Keuangan)' },
          ]} />
        </GlassCard>
      </div>
    </div>
  );
}
