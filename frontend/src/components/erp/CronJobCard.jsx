import { useEffect, useState } from 'react';
import { Clock, Play } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { apiGet, apiPost } from '../../lib/api';

/** Kartu status cron platform (jalankan sekarang + riwayat terakhir). job: 'mark-overdue' | 'fg-valuation-check' */
export default function CronJobCard({ job, title, description, renderResult, onRan }) {
  const [runs, setRuns] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = () => apiGet(`/cron/runs?job=${job}&limit=3`).then(setRuns).catch(() => {});
  useEffect(() => { load(); }, [job]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setBusy(true);
    try { const r = await apiPost(`/cron/${job}/run-now`, {}); toast.success('Selesai dijalankan'); load(); onRan?.(r.result); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const last = runs[0];
  return (
    <GlassCard className="p-4" data-testid={`cron-card-${job}`}>
      <div className="flex flex-wrap items-center gap-3">
        <Clock className="w-4 h-4 text-sky-300" />
        <div className="text-sm"><span className="font-semibold">{title}</span> <span className="text-muted-foreground">— {description}</span></div>
        <Button size="sm" variant="ghost" className="ml-auto border border-[var(--glass-border)]" disabled={busy} onClick={run} data-testid={`cron-run-${job}`}><Play className="w-3.5 h-3.5 mr-1" />Jalankan sekarang</Button>
      </div>
      <div className="mt-2 text-xs text-muted-foreground" data-testid={`cron-last-${job}`}>
        {last ? <>Terakhir: {new Date(last.started_at).toLocaleString('id-ID')} · {last.trigger} · {last.status}{last.result && renderResult ? ` · ${renderResult(last.result)}` : ''}{last.error ? ` · ${last.error}` : ''}</> : 'Belum pernah dijalankan.'}
      </div>
    </GlassCard>
  );
}
