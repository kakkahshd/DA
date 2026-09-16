import { useState, useEffect, useCallback, useRef } from 'react';
import { Download, Upload, Lock, CheckCircle2, AlertTriangle, RefreshCw, FileSpreadsheet, ShieldCheck } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, fmtCell, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'py-1.5 px-2 text-right font-mono text-xs';

function PostedJournal({ status, onVoided, token, role }) {
  const je = status.journal;
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const canVoid = ['superadmin', 'owner'].includes((role || '').toLowerCase());
  const doVoid = async () => {
    if (!reason.trim()) { toast.error('Alasan wajib diisi'); return; }
    setBusy(true);
    try {
      const r = await fetch(`/api/rahaza/journals/${je.id}/void`, { method: 'POST', headers: { ...authHeaders(token), 'Content-Type': 'application/json' }, body: JSON.stringify({ reason, force: true }) });
      const j = await r.json();
      if (!r.ok) { toast.error(j.detail || 'Gagal membatalkan'); return; }
      toast.success(`Jurnal ${je.je_number} dibatalkan — saldo awal bisa diunggah ulang`);
      onVoided();
    } finally { setBusy(false); }
  };
  return (
    <GlassCard className="p-5 space-y-4" data-testid="ob-posted">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="inline-flex items-center gap-2 text-emerald-300 font-semibold"><Lock className="w-4 h-4" />Saldo awal sudah diposting & terkunci</div>
          <p className="text-xs text-muted-foreground mt-1">
            Jurnal <span className="font-mono text-foreground" data-testid="ob-je-number">{je.je_number}</span> · tanggal {je.date} · {status.lines.length} baris ·
            D {fmt(je.total_debit)} = K {fmt(je.total_credit)} · {je.source_ref}
          </p>
        </div>
      </div>
      <div className="overflow-auto max-h-[50vh]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground">
            <tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Kode</th><th className="py-2 px-2 text-left">Akun</th><th className="py-2 px-2 text-right">Debit</th><th className="py-2 px-2 text-right">Kredit</th></tr>
          </thead>
          <tbody>
            {status.lines.map((l) => (
              <tr key={l.line_id} className="border-b border-[var(--glass-border)]" data-testid={`ob-line-${l.account_code}`}>
                <td className="py-1.5 px-2 font-mono text-xs">{l.account_code}</td><td className="py-1.5 px-2 text-xs">{l.account_name}</td>
                <td className={tdN}>{fmtCell(l.debit)}</td><td className={tdN}>{fmtCell(l.credit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canVoid && (
        <div className="border-t border-[var(--glass-border)] pt-4 space-y-2">
          <p className="text-xs text-muted-foreground">Salah isi? Superadmin dapat membatalkan jurnal ini (void paksa, tercatat di audit) lalu mengunggah ulang.</p>
          <div className="flex gap-2 flex-wrap">
            <GlassInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan pembatalan (wajib)" className="h-9 flex-1 min-w-[220px]" data-testid="ob-void-reason" />
            <Button variant="ghost" onClick={doVoid} disabled={busy} className="h-9 border border-rose-500/40 text-rose-300" data-testid="ob-void-btn">Batalkan Jurnal Saldo Awal</Button>
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function PreviewTable({ preview }) {
  const errRows = preview.rows.filter((r) => r.error);
  return (
    <div className="space-y-3" data-testid="ob-preview">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Baris terisi" value={preview.rows.length} testId="ob-kpi-rows" />
        <StatTile label="Total Debit" value={fmt(preview.totals.debit)} testId="ob-kpi-debit" />
        <StatTile label="Total Kredit" value={fmt(preview.totals.credit)} testId="ob-kpi-credit" />
        <StatTile label={preview.ok ? 'Siap diposting' : `${preview.errors.length} masalah`} value={preview.ok ? '✓' : '✗'} accent={preview.ok ? 'success' : 'danger'} testId="ob-kpi-status" />
      </div>
      {preview.errors.length > 0 && (
        <GlassCard className="p-4 border border-rose-500/30" data-testid="ob-errors">
          <div className="inline-flex items-center gap-2 text-rose-300 font-semibold text-sm mb-2"><AlertTriangle className="w-4 h-4" />Perbaiki dulu di Excel, lalu unggah lagi</div>
          <ul className="text-xs space-y-1 list-disc pl-5">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </GlassCard>
      )}
      {preview.balancing && (
        <GlassCard className="p-3 text-xs text-amber-200" data-testid="ob-balancing">
          Selisih Rp {fmt(Math.max(preview.balancing.debit, preview.balancing.credit))} ditutup otomatis ke {preview.balancing.account_code} {preview.balancing.account_name} ({preview.balancing.debit ? 'debit' : 'kredit'}).
        </GlassCard>
      )}
      {preview.relations?.length > 0 && (
        <GlassCard className="p-0 overflow-hidden">
          <div className="px-4 py-2 text-[10px] uppercase text-muted-foreground border-b border-[var(--glass-border)]">Rincian per relasi vs akun kontrol</div>
          <table className="w-full text-sm">
            <tbody>
              {preview.relations.map((r) => (
                <tr key={r.sheet} className="border-b border-[var(--glass-border)] last:border-0" data-testid={`ob-rel-${r.sheet}`}>
                  <td className="py-1.5 px-4 text-xs font-mono">{r.sheet}</td>
                  <td className="py-1.5 px-2 text-xs text-muted-foreground">{r.rows} baris → {r.control_account}</td>
                  <td className={tdN}>{fmt(r.detail_total)}</td>
                  <td className={tdN}>vs {fmt(r.control_balance)}</td>
                  <td className={`py-1.5 px-4 text-xs ${r.match ? 'text-emerald-300' : 'text-rose-300'}`}>{r.match ? (r.rows ? 'cocok' : 'kosong') : 'TIDAK cocok'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}
      <GlassCard className="p-0 overflow-hidden">
        <div className="overflow-auto max-h-[45vh]">
          <table className="w-full text-sm" data-testid="ob-preview-table">
            <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground">
              <tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Baris</th><th className="py-2 px-2 text-left">Kode</th><th className="py-2 px-2 text-left">Akun</th><th className="py-2 px-2 text-right">Debit</th><th className="py-2 px-2 text-right">Kredit</th><th className="py-2 px-2 text-left">Status</th></tr>
            </thead>
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.row} className={`border-b border-[var(--glass-border)] ${r.error ? 'bg-rose-500/10' : ''}`} data-testid={`ob-row-${r.code}`}>
                  <td className="py-1.5 px-2 text-xs text-muted-foreground">{r.row}</td>
                  <td className="py-1.5 px-2 font-mono text-xs">{r.code}</td>
                  <td className="py-1.5 px-2 text-xs">{r.name}</td>
                  <td className={tdN}>{fmtCell(r.debit)}</td><td className={tdN}>{fmtCell(r.credit)}</td>
                  <td className={`py-1.5 px-2 text-xs ${r.error ? 'text-rose-300' : 'text-emerald-300'}`}>{r.error || 'OK'}</td>
                </tr>
              ))}
              {preview.rows.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-muted-foreground text-xs">Semua saldo 0 — tidak ada yang akan diposting.</td></tr>}
            </tbody>
          </table>
        </div>
      </GlassCard>
      {errRows.length > 0 && <p className="text-[11px] text-muted-foreground">{errRows.length} baris bermasalah ditandai merah.</p>}
    </div>
  );
}

export default function RahazaOpeningBalanceModule({ token, user }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [file, setFile] = useState(null);
  const [obDate, setObDate] = useState(`${new Date().getFullYear()}-01-01`);
  const [toRetained, setToRetained] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/finance/opening-balance/status', { headers: authHeaders(token) });
      if (r.ok) setStatus(await r.json());
    } finally { setLoading(false); }
  }, [token]);
  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const form = () => { const fd = new FormData(); fd.append('file', file); fd.append('balance_to_retained', toRetained ? 'true' : 'false'); return fd; };

  const doPreview = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await fetch('/api/rahaza/finance/opening-balance/preview', { method: 'POST', headers: authHeaders(token), body: form() });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : 'Gagal membaca berkas'); setPreview(null); return; }
      setPreview(j);
    } finally { setBusy(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, toRetained, token]);
  useEffect(() => { doPreview(); }, [doPreview]);

  const doApply = async () => {
    if (!preview?.ok) return;
    setBusy(true);
    try {
      const fd = form(); fd.append('ob_date', obDate);
      const r = await fetch('/api/rahaza/finance/opening-balance/apply', { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : j.detail?.message || 'Posting gagal'); return; }
      toast.success(`Saldo awal diposting: ${j.journal.je_number}`);
      setFile(null); setPreview(null); if (inputRef.current) inputRef.current.value = '';
      fetchStatus();
    } finally { setBusy(false); }
  };

  const dlTemplate = () => downloadXlsx('/api/rahaza/finance/opening-balance/template', token, 'SALDO_AWAL_GOLIVE.xlsx').catch((e) => toast.error(`Unduh gagal: ${e.message}`));

  return (
    <div className="space-y-5" data-testid="ob-page">
      <PageHeader
        icon={ShieldCheck}
        eyebrow="Portal Finance · Master Akuntansi"
        title="Saldo Awal Neraca (Go-Live)"
        subtitle="Pindahkan neraca penutup pembukuan lama ke sistem: unduh template, isi debit/kredit per akun (+ rincian piutang/hutang per relasi), unggah untuk diperiksa, lalu posting SATU jurnal pembuka yang terkunci."
        actions={<Button variant="ghost" onClick={fetchStatus} className="h-9 border border-[var(--glass-border)]" data-testid="ob-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>}
      />
      {loading ? <Skeleton className="h-40 rounded-xl" /> : status?.journal ? (
        <PostedJournal status={status} token={token} role={user?.role} onVoided={fetchStatus} />
      ) : (
        <>
          <div className="grid md:grid-cols-3 gap-4">
            <GlassCard className="p-5 space-y-3" data-testid="ob-step-1">
              <div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 1</div>
              <h3 className="font-semibold text-sm">Unduh template</h3>
              <p className="text-xs text-muted-foreground">{status?.balance_accounts || 0} akun neraca aktif + sheet rincian {status?.relation_sheets?.map((s) => s.control_account).join(', ')}.</p>
              <Button onClick={dlTemplate} className="h-9 w-full" data-testid="ob-download-template"><Download className="w-3.5 h-3.5 mr-1.5" />Template Excel</Button>
            </GlassCard>
            <GlassCard className="p-5 space-y-3" data-testid="ob-step-2">
              <div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 2</div>
              <h3 className="font-semibold text-sm">Unggah berkas terisi</h3>
              <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/20 file:px-3 file:py-1.5 file:text-xs file:text-primary" data-testid="ob-file-input" />
              <label className="inline-flex items-center gap-2 text-xs text-foreground/80">
                <input type="checkbox" checked={toRetained} onChange={(e) => setToRetained(e.target.checked)} data-testid="ob-to-retained" />
                Tutup selisih D≠K ke 3-2000 Laba Ditahan
              </label>
            </GlassCard>
            <GlassCard className="p-5 space-y-3" data-testid="ob-step-3">
              <div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 3</div>
              <h3 className="font-semibold text-sm">Posting jurnal pembuka</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Per tanggal</span>
                <GlassInput type="date" value={obDate} onChange={(e) => setObDate(e.target.value)} className="h-8 w-36" data-testid="ob-date" />
              </div>
              <Button onClick={doApply} disabled={!preview?.ok || !preview.lines?.length || busy} className="h-9 w-full" data-testid="ob-apply">
                {preview?.ok ? <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" /> : <Upload className="w-3.5 h-3.5 mr-1.5" />}Posting Saldo Awal
              </Button>
            </GlassCard>
          </div>
          {busy && !preview && <Skeleton className="h-24 rounded-xl" />}
          {preview ? <PreviewTable preview={preview} /> : (
            <GlassCard className="p-8 text-center text-muted-foreground text-sm" data-testid="ob-empty">
              <FileSpreadsheet className="w-8 h-8 mx-auto mb-2 opacity-40" />Belum ada berkas — pratinjau muncul otomatis setelah berkas dipilih. Tidak ada yang tersimpan sebelum tombol Posting ditekan.
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}
