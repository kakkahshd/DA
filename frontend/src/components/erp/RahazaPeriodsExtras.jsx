import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, BookLock, Undo2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';

const fmt = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));

export function PeriodAlerts({ headers, onOpened }) {
  const [alerts, setAlerts] = useState([]);
  const load = useCallback(async () => {
    const r = await fetch('/api/rahaza/periods/alerts', { headers });
    if (r.ok) setAlerts((await r.json()).alerts || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { load(); }, [load]);

  const openYear = async (y) => {
    const r = await fetch('/api/rahaza/periods/ensure-year', { method: 'POST', headers, body: JSON.stringify({ year: y }) });
    if (r.ok) { await load(); onOpened?.(y); } else { const e = await r.json(); alert(e.detail || 'Error'); }
  };
  const resolve = async (id) => {
    await fetch(`/api/rahaza/periods/alerts/${id}/resolve`, { method: 'POST', headers });
    load();
  };
  if (!alerts.length) return null;
  return (
    <GlassCard className="p-4 border-red-400/30" data-testid="period-alerts-card">
      <div className="flex items-center gap-2 text-red-300 text-sm font-semibold mb-2">
        <AlertTriangle className="w-4 h-4" /> {alerts.length} jurnal ditolak — periode belum dibuka
      </div>
      <div className="space-y-2">
        {alerts.map(a => (
          <div key={a.id} className="flex flex-wrap items-center gap-3 text-xs rounded-md bg-red-400/5 border border-red-400/15 px-3 py-2" data-testid={`period-alert-${a.id}`}>
            <div className="flex-1 min-w-[240px]">
              <div className="font-medium text-foreground/90">Tahun {a.year} · modul <span className="font-mono">{a.source_module}</span> · {a.count}× ditolak</div>
              <div className="text-foreground/60">{a.message}</div>
              {a.memo && <div className="text-foreground/50 italic">Terakhir: {a.memo}</div>}
            </div>
            <Button size="sm" onClick={() => openYear(a.year)} data-testid={`period-alert-open-${a.id}`}>Buka tahun {a.year}</Button>
            <Button size="sm" variant="ghost" onClick={() => resolve(a.id)} data-testid={`period-alert-resolve-${a.id}`}>Abaikan</Button>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

export function YearEndClose({ headers, year, onDone }) {
  const [preview, setPreview] = useState(null);
  const [closings, setClosings] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [p, c] = await Promise.all([
      fetch(`/api/rahaza/year-end/preview?year=${year}`, { headers }),
      fetch('/api/rahaza/year-end', { headers }),
    ]);
    if (p.ok) setPreview(await p.json());
    if (c.ok) setClosings((await c.json()).closings || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const doClose = async () => {
    if (!window.confirm(`Tutup tahun ${year}? Semua akun L/R di-nol-kan dan laba bersih Rp ${fmt(preview.net_income)} dipindah ke Laba Ditahan (3-2000).`)) return;
    setBusy(true);
    const r = await fetch('/api/rahaza/year-end/close', { method: 'POST', headers, body: JSON.stringify({ year }) });
    setBusy(false);
    if (r.ok) { await load(); onDone?.(); } else { const e = await r.json(); alert(e.detail || 'Error'); }
  };
  const doReverse = async () => {
    if (!window.confirm(`Batalkan jurnal penutup tahun ${year}?`)) return;
    const r = await fetch(`/api/rahaza/year-end/${year}/reverse`, { method: 'POST', headers });
    if (r.ok) { await load(); onDone?.(); } else { const e = await r.json(); alert(e.detail || 'Error'); }
  };
  if (!preview) return null;
  const closed = preview.already_closed;
  return (
    <GlassCard className="p-4" data-testid="year-end-card">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <BookLock className="w-4 h-4 text-violet-300" />
        <div className="text-sm font-semibold">Tutup Tahun {year}</div>
        <span className={`text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded border ${closed ? 'text-violet-300 bg-violet-400/10 border-violet-400/25' : 'text-foreground/60 border-foreground/10'}`} data-testid="year-end-status">
          {closed ? `Sudah ditutup · ${preview.existing_je?.je_number}` : 'Belum ditutup'}
        </span>
        <div className="ml-auto flex gap-2">
          {!closed && <Button size="sm" disabled={!preview.can_close || busy} onClick={doClose} data-testid="year-end-close-btn">Tutup Tahun {year}</Button>}
          {closed && <Button size="sm" variant="ghost" onClick={doReverse} data-testid="year-end-reverse-btn"><Undo2 className="w-3.5 h-3.5 mr-1" />Batalkan penutupan</Button>}
        </div>
      </div>
      <div className="grid sm:grid-cols-3 gap-3 text-xs">
        <div className="rounded-md bg-foreground/5 px-3 py-2">
          <div className="text-foreground/50">Laba (rugi) bersih {year}</div>
          <div className="text-base font-semibold" data-testid="year-end-net-income">Rp {fmt(preview.net_income)}</div>
        </div>
        <div className="rounded-md bg-foreground/5 px-3 py-2">
          <div className="text-foreground/50">Akun L/R bersaldo</div>
          <div className="text-base font-semibold">{preview.lines?.length || 0} akun</div>
        </div>
        <div className="rounded-md bg-foreground/5 px-3 py-2">
          <div className="text-foreground/50">Periode belum closed</div>
          <div className={`text-base font-semibold ${preview.open_periods?.length ? 'text-amber-300' : 'text-emerald-300'}`} data-testid="year-end-open-periods">
            {preview.open_periods?.length ? preview.open_periods.map(p => p.slice(5)).join(', ') : 'semua closed'}
          </div>
        </div>
      </div>
      {!closed && !preview.can_close && (
        <div className="mt-2 text-[11px] text-foreground/55">
          Syarat: 12 periode closed/locked, ada saldo L/R, akun Laba Ditahan {preview.retained_earnings_account} aktif.
        </div>
      )}
      {closings.length > 0 && (
        <div className="mt-3 text-[11px] text-foreground/60" data-testid="year-end-history">
          Riwayat: {closings.map(c => `${c.year} → ${c.je_number} (${c.status}, Rp ${fmt(c.net_income)})`).join(' · ')}
        </div>
      )}
    </GlassCard>
  );
}
