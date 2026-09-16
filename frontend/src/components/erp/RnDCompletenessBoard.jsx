import { useEffect, useState, useMemo } from 'react';
import { ClipboardCheck, ArrowUpRight, CheckCircle2, XCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';

const API = process.env.REACT_APP_BACKEND_URL || '';
// Tujuan navigasi per jenis kekurangan (hub + tab)
const TARGET = {
  bom: ['rnd-master-product-hub', 'bom'], accessories: ['rnd-master-product-hub', 'bom'], hpp: ['rnd-master-product-hub', 'bom'],
  techpack: ['rnd-design-hub', 'techpack'], photo: ['rnd-master-product-hub', 'models'], weight: ['rnd-master-product-hub', 'models'], sop: ['rnd-master-product-hub', 'models'],
};

export function RnDCompletenessBoard({ token, onNavigate }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState('all');
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/dewi/rnd/completeness`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null)).then(setData).catch(() => setData(null));
  }, [token]);

  const rows = useMemo(() => {
    if (!data) return [];
    const r = filter === 'all' ? data.rows.filter((x) => x.missing.length) : data.rows.filter((x) => x.missing.includes(filter));
    return showAll ? r : r.slice(0, 12);
  }, [data, filter, showAll]);

  const go = (key, modelId) => {
    const [hub, tab] = TARGET[key] || ['rnd-master-product-hub', 'models'];
    try { sessionStorage.setItem(`hub_tab_${hub}`, tab); if (modelId) sessionStorage.setItem('bom_jump_model', modelId); } catch { /* abaikan */ }
    onNavigate && onNavigate(hub);
  };

  if (!data) return <Skeleton className="h-40 rounded-xl" />;
  const pct = data.total_models ? Math.round((100 * data.complete_models) / data.total_models) : 0;

  return (
    <GlassCard className="p-5 space-y-4" data-testid="rnd-completeness-board">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold"><ClipboardCheck className="h-4 w-4 text-primary" /> Papan Kelengkapan Data Produk</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            <span className="font-mono" data-testid="rnd-completeness-summary">{data.complete_models}/{data.total_models}</span> model lengkap ({pct}%). Klik kartu untuk melihat model yang kurang, klik panah untuk langsung ke layar pengisiannya.
          </p>
        </div>
        <button onClick={() => setFilter('all')} className={`text-xs px-3 py-1 rounded-full border border-[var(--glass-border)] ${filter === 'all' ? 'bg-primary/15 text-primary' : 'text-muted-foreground'}`} data-testid="rnd-completeness-filter-all">Semua kekurangan</button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        {data.checks.map((c) => {
          const n = data.missing_counts[c.key] || 0;
          return (
            <button key={c.key} onClick={() => setFilter(c.key)}
              className={`text-left rounded-lg border p-3 transition-colors ${filter === c.key ? 'border-primary/50 bg-primary/10' : 'border-[var(--glass-border)] hover:bg-foreground/5'}`}
              data-testid={`rnd-completeness-card-${c.key}`}>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{c.label}</div>
              <div className={`text-xl font-bold font-mono ${n ? 'text-amber-400' : 'text-emerald-400'}`}>{n}</div>
              <div className="text-[10px] text-muted-foreground">{n ? 'model kurang' : 'semua lengkap'}</div>
            </button>
          );
        })}
      </div>
      <div className="overflow-auto max-h-[46vh]">
        <table className="w-full text-sm" data-testid="rnd-completeness-table">
          <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground">
            <tr className="border-b border-[var(--glass-border)]">
              <th className="py-2 px-2 text-left">Model</th><th className="py-2 px-2 text-left">Kategori</th>
              {data.checks.map((c) => <th key={c.key} className="py-2 px-1 text-center whitespace-nowrap">{c.label}</th>)}
              <th className="py-2 px-2 text-right">Skor</th><th className="py-2 px-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model_id} className="border-b border-[var(--glass-border)] hover:bg-foreground/5" data-testid={`rnd-completeness-row-${r.code}`}>
                <td className="py-1.5 px-2 whitespace-nowrap"><span className="font-mono text-xs text-muted-foreground mr-2">{r.code}</span>{r.name}</td>
                <td className="py-1.5 px-2 text-xs text-muted-foreground">{r.category}</td>
                {data.checks.map((c) => (
                  <td key={c.key} className="py-1.5 px-1 text-center">
                    {r.flags[c.key] ? <CheckCircle2 className="h-4 w-4 text-emerald-400 inline" /> : (
                      <button onClick={() => go(c.key, r.model_id)} title={`Isi ${c.label} untuk ${r.code}`} data-testid={`rnd-completeness-fix-${r.code}-${c.key}`}>
                        <XCircle className="h-4 w-4 text-rose-400 inline hover:scale-110 transition-transform" />
                      </button>
                    )}
                    {c.key === 'bom' && r.variants_without_bom > 0 && <div className="text-[9px] text-amber-400">{r.variants_without_bom}/{r.variants} varian</div>}
                  </td>
                ))}
                <td className="py-1.5 px-2 text-right font-mono text-xs">{r.score}%</td>
                <td className="py-1.5 px-2 text-right">
                  <button onClick={() => go(r.missing[0] || 'bom', r.model_id)} className="text-primary hover:underline text-xs inline-flex items-center gap-1" data-testid={`rnd-completeness-go-${r.code}`}>isi <ArrowUpRight className="h-3 w-3" /></button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={data.checks.length + 4} className="py-6 text-center text-xs text-muted-foreground">Tidak ada model yang kurang pada kriteria ini 🎉</td></tr>}
          </tbody>
        </table>
      </div>
      {!showAll && data.rows.filter((x) => filter === 'all' ? x.missing.length : x.missing.includes(filter)).length > 12 && (
        <button onClick={() => setShowAll(true)} className="text-xs text-primary hover:underline" data-testid="rnd-completeness-more">Tampilkan semua model…</button>
      )}
    </GlassCard>
  );
}
