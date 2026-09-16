/**
 * WithdrawalImportPanel — pratinjau impor laporan penarikan Shopee/TikTok (tahap 2).
 * Kolom yang dipakai ditampilkan & bisa diganti; baris bermasalah ditandai, bukan dibuang.
 */
import { useMemo, useState } from 'react';
import { X, Loader2, CheckCircle2, AlertTriangle, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { formatRupiah as rp } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL;
const ROLES = [['date', 'Tanggal'], ['amount', 'Nominal'], ['reference', 'No. penarikan'], ['status', 'Status'], ['bank', 'Rekening']];

export async function previewWithdrawalFile(file, accountId, mapping) {
  const fd = new FormData();
  fd.append('file', file);
  if (accountId) fd.append('account_id', accountId);
  if (mapping) fd.append('mapping', JSON.stringify(mapping));
  const r = await fetch(`${API}/api/marketing/withdrawals/import/preview`, {
    method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` }, body: fd,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Gagal membaca berkas (HTTP ${r.status})`);
  return d;
}

export function WithdrawalImportPanel({ result, file, accounts, accountId, onAccountChange, onResult, onClose, onCommitted }) {
  const [busy, setBusy] = useState('');
  const [excluded, setExcluded] = useState({});
  const rows = result?.rows || [];
  const selected = useMemo(() => rows.filter((r) => r.ok && !excluded[r.row]), [rows, excluded]);
  const total = selected.reduce((t, r) => t + (r.amount || 0), 0);

  const remap = async (role, header) => {
    setBusy('map');
    try { onResult(await previewWithdrawalFile(file, accountId, { ...result.mapping, [role]: header || null })); }
    catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const changeAccount = async (id) => {
    onAccountChange(id);
    setBusy('map');
    try { onResult(await previewWithdrawalFile(file, id, result.mapping)); }
    catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const commit = async () => {
    if (!accountId) { toast.error('Pilih toko dulu.'); return; }
    if (!selected.length) { toast.error('Tidak ada baris yang bisa disimpan.'); return; }
    setBusy('commit');
    try {
      const r = await fetch(`${API}/api/marketing/withdrawals/import/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('erp_token')}` },
        body: JSON.stringify({ account_id: accountId, filename: result.filename,
          rows: selected.map((r) => ({ withdrawal_date: r.withdrawal_date, amount: r.amount, reference: r.reference || '' })) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Gagal menyimpan (HTTP ${r.status})`);
      toast.success(d.message);
      onCommitted?.(d);
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  if (!result) return null;
  return (
    <div className="rounded-lg border border-foreground/10 p-3 space-y-3" data-testid="wd-import-panel">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-medium flex items-center gap-2">
          <Upload className="w-4 h-4" /> Pratinjau impor — {result.filename}
          <span className="text-xs text-foreground/50 font-normal">{result.row_count} baris · terdeteksi {result.platform_guess || 'platform tak dikenal'}</span>
        </h4>
        <button data-testid="wd-import-close" onClick={onClose} className="p-1 rounded hover:bg-foreground/10"><X className="w-4 h-4" /></button>
      </div>

      <div className="grid md:grid-cols-6 gap-2 text-xs">
        <label className="space-y-1">
          <span className="text-foreground/60">Toko</span>
          <select data-testid="wd-import-account" value={accountId} onChange={(e) => changeAccount(e.target.value)}
            className="w-full h-8 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-xs">
            <option value="">— pilih toko —</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name} · {a.platform}</option>)}
          </select>
        </label>
        {ROLES.map(([role, label]) => (
          <label key={role} className="space-y-1">
            <span className="text-foreground/60">Kolom {label}</span>
            <select data-testid={`wd-import-map-${role}`} value={result.mapping?.[role] || ''} disabled={busy === 'map'}
              onChange={(e) => remap(role, e.target.value)}
              className="w-full h-8 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-xs">
              <option value="">— tidak dipakai —</option>
              {(result.headers || []).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
        ))}
      </div>

      {accountId ? (
        <div className="text-xs text-foreground/60" data-testid="wd-import-balance">
          Saldo platform toko: <b className="text-foreground">{rp(result.available_balance || 0)}</b>
          {result.cash_code ? <> · masuk ke rekening <span className="font-mono">{result.cash_code}</span></> : <> · <span className="text-amber-600">rekening pencairan belum ditautkan</span></>}
        </div>
      ) : null}

      <div className="max-h-72 overflow-auto rounded-lg border border-foreground/10">
        <table className="w-full text-xs" data-testid="wd-import-table">
          <thead className="sticky top-0 bg-background">
            <tr className="text-[10px] uppercase tracking-wide text-foreground/50 border-b border-foreground/10">
              <th className="px-2 py-1.5 text-left">Simpan</th>
              <th className="px-2 py-1.5 text-left">#</th>
              <th className="px-2 py-1.5 text-left">Tanggal</th>
              <th className="px-2 py-1.5 text-left">No. penarikan</th>
              <th className="px-2 py-1.5 text-right">Nominal</th>
              <th className="px-2 py-1.5 text-left">Status</th>
              <th className="px-2 py-1.5 text-left">Keterangan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.row} className={`border-b border-foreground/5 ${r.ok ? '' : 'opacity-60'}`} data-testid={`wd-import-row-${r.row}`}>
                <td className="px-2 py-1"><input type="checkbox" disabled={!r.ok} checked={r.ok && !excluded[r.row]}
                  onChange={(e) => setExcluded({ ...excluded, [r.row]: !e.target.checked })} data-testid={`wd-import-check-${r.row}`} /></td>
                <td className="px-2 py-1 text-foreground/50">{r.row}</td>
                <td className="px-2 py-1">{r.withdrawal_date || '—'}</td>
                <td className="px-2 py-1 font-mono">{r.reference || <span className="text-foreground/40">otomatis</span>}</td>
                <td className="px-2 py-1 text-right tabular-nums">{r.amount != null ? rp(r.amount) : '—'}</td>
                <td className="px-2 py-1">{r.status || '—'}</td>
                <td className="px-2 py-1">
                  {r.ok ? <span className="text-emerald-600 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> siap</span>
                    : <span className="text-amber-600 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {r.reason}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs" data-testid="wd-import-summary">
          <b>{selected.length}</b> baris akan disimpan · total <b>{rp(total)}</b>
          {rows.length - rows.filter((r) => r.ok).length ? <span className="text-foreground/50"> · {rows.length - rows.filter((r) => r.ok).length} baris ditandai bermasalah</span> : null}
        </div>
        <button data-testid="wd-import-commit" disabled={busy === 'commit' || !selected.length || !accountId} onClick={commit}
          className="h-9 px-4 rounded-lg bg-primary text-primary-foreground text-sm flex items-center gap-1.5 disabled:opacity-50">
          {busy === 'commit' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
          Simpan {selected.length} penarikan
        </button>
      </div>
    </div>
  );
}
