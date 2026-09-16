/**
 * PlatformWithdrawalsPanel — TAHAP 2: penarikan saldo platform ke rekening bank.
 * Jurnal: Dr Rekening Pencairan toko / Cr Piutang Toko (1-1303-xxx). Dokumen inilah
 * yang dicocokkan ke mutasi bank di Rekonsiliasi Bank.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine, Plus, X, Loader2, CheckCircle2, BookCheck, Send, Pencil, Trash2, Landmark, Upload,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { toast } from 'sonner';
import { formatRupiah as rp } from '@/lib/format';
import { WithdrawalImportPanel, previewWithdrawalFile } from './WithdrawalImportPanel';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/marketing/withdrawals`;

async function call(path, opts = {}) {
  const r = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('erp_token')}` },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.message || `Gagal (HTTP ${r.status})`);
  return d;
}

const EMPTY = { account_id: '', withdrawal_date: '', amount: '', reference: '', notes: '' };

export function PlatformWithdrawalsPanel({ accounts, accountId, balances, onChanged }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState('');
  const [importRes, setImportRes] = useState(null);
  const [importFile, setImportFile] = useState(null);
  const [importAccount, setImportAccount] = useState('');
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ page_size: '50' });
      if (accountId) qs.set('account_id', accountId);
      const d = await call(`?${qs}`);
      setRows(d.data || []); setSummary(d.summary || null);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [accountId]);
  useEffect(() => { load(); }, [load]);

  const accName = (id) => accounts.find((a) => a.id === id)?.account_name || id || '—';
  const balanceOf = useMemo(() => {
    const m = {};
    (balances || []).forEach((b) => { m[b.account_id] = b; });
    return m;
  }, [balances]);
  const selBal = balanceOf[form.account_id];
  const available = selBal ? selBal.balance + (editId ? (rows.find((r) => r.id === editId)?.amount || 0) : 0) : null;

  const openCreate = () => { setForm({ ...EMPTY, account_id: accountId || '' }); setEditId(''); setFormOpen(true); };
  const openEdit = (r) => {
    setForm({ account_id: r.account_id, withdrawal_date: r.withdrawal_date || '', amount: String(r.amount ?? ''),
      reference: r.reference || '', notes: r.notes || '' });
    setEditId(r.id); setFormOpen(true);
  };

  const refresh = async () => { await load(); onChanged?.(); };

  const startImport = async (file) => {
    if (!file) return;
    setBusy('import');
    try {
      let acc = accountId || '';
      let d = await previewWithdrawalFile(file, acc);
      if (!acc && d.platform_guess) {
        const cand = accounts.filter((a) => a.platform === d.platform_guess);
        if (cand.length === 1) { acc = cand[0].id; d = await previewWithdrawalFile(file, acc); }
      }
      setImportFile(file); setImportAccount(acc); setImportRes(d); setFormOpen(false);
      toast.success(`${d.ok_count} dari ${d.row_count} baris siap disimpan — periksa kolom & toko lalu simpan.`);
      if (!acc) toast.warning('Toko belum dipilih — pilih toko yang benar sebelum menyimpan.');
    } catch (e) { toast.error(e.message); } finally {
      setBusy('');
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const save = async () => {
    if (!form.account_id) { toast.error('Pilih toko dulu.'); return; }
    if (!form.withdrawal_date) { toast.error('Tanggal uang masuk bank wajib diisi.'); return; }
    if (!(parseFloat(form.amount) > 0)) { toast.error('Nominal penarikan harus lebih dari 0.'); return; }
    setBusy('save');
    try {
      const body = { ...form, amount: parseFloat(form.amount) };
      await (editId ? call(`/${editId}`, { method: 'PUT', body: JSON.stringify(body) })
        : call('', { method: 'POST', body: JSON.stringify(body) }));
      toast.success(editId ? 'Penarikan diperbarui.' : 'Penarikan saldo tercatat — saldo platform toko berkurang.');
      setFormOpen(false);
      await refresh();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const act = async (r, kind) => {
    setBusy(`${kind}:${r.id}`);
    try {
      if (kind === 'journal') toast.success((await call(`/${r.id}/journal`, { method: 'POST' })).message);
      else if (kind === 'post') toast.success((await call(`/${r.id}/post`, { method: 'POST' })).message);
      else if (kind === 'delete') { await call(`/${r.id}`, { method: 'DELETE' }); toast.success('Penarikan dihapus.'); }
      await refresh();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  return (
    <GlassCard className="p-4 space-y-3" data-testid="platform-withdrawals-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium text-sm flex items-center gap-2">
            <ArrowDownToLine className="w-4 h-4" /> Tahap 2 — Penarikan Saldo ke Bank
          </h3>
          <p className="text-xs text-foreground/60 mt-0.5">
            Uang yang benar-benar masuk rekening dari saldo platform. Jurnal: <b>Dr Rekening Pencairan / Cr Piutang Toko</b>.
            Inilah yang dicocokkan ke mutasi bank. Total ditarik: <b>{rp(summary?.amount || 0)}</b>
            {summary ? ` · ${summary.bank_linked_count} tertaut mutasi bank` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.tsv" className="hidden" data-testid="wd-import-file"
            onChange={(e) => startImport(e.target.files?.[0])} />
          <button data-testid="wd-import" disabled={busy === 'import'} onClick={() => fileRef.current?.click()}
            title="Unggah laporan penarikan / withdrawal Shopee atau TikTok"
            className="h-9 px-3 rounded-lg bg-foreground/5 hover:bg-foreground/10 text-sm flex items-center gap-1.5 disabled:opacity-50">
            {busy === 'import' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Impor laporan penarikan
          </button>
          <button data-testid="wd-new" onClick={openCreate}
            className="h-9 px-3 rounded-lg bg-primary text-primary-foreground text-sm flex items-center gap-1.5">
            <Plus className="w-4 h-4" /> Catat penarikan
          </button>
        </div>
      </div>

      <WithdrawalImportPanel result={importRes} file={importFile} accounts={accounts} accountId={importAccount}
        onAccountChange={setImportAccount} onResult={setImportRes} onClose={() => setImportRes(null)}
        onCommitted={async () => { setImportRes(null); await refresh(); }} />

      {formOpen ? (
        <div className="rounded-lg border border-foreground/10 p-3 space-y-3" data-testid="wd-form">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">{editId ? 'Koreksi penarikan' : 'Catat penarikan saldo'}</h4>
            <button data-testid="wd-form-close" onClick={() => setFormOpen(false)} className="p-1 rounded hover:bg-foreground/10"><X className="w-4 h-4" /></button>
          </div>
          <div className="grid md:grid-cols-5 gap-3">
            <label className="text-xs space-y-1">
              <span className="text-foreground/60">Toko</span>
              <select data-testid="wd-input-account" value={form.account_id}
                onChange={(e) => setForm({ ...form, account_id: e.target.value })}
                className="w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm">
                <option value="">— pilih toko —</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name} · {a.platform}</option>)}
              </select>
            </label>
            <label className="text-xs space-y-1">
              <span className="text-foreground/60">Tanggal masuk bank</span>
              <input type="date" data-testid="wd-input-date" value={form.withdrawal_date}
                onChange={(e) => setForm({ ...form, withdrawal_date: e.target.value })}
                className="w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-foreground/60">Nominal (menurut mutasi bank)</span>
              <input type="number" step="1" data-testid="wd-input-amount" value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm text-right tabular-nums font-semibold" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-foreground/60">No. penarikan (platform, opsional)</span>
              <input data-testid="wd-input-reference" value={form.reference}
                onChange={(e) => setForm({ ...form, reference: e.target.value })}
                className="w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm font-mono" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-foreground/60">Catatan</span>
              <input data-testid="wd-input-notes" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                className="w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm" />
            </label>
          </div>
          {form.account_id ? (
            <div className={`text-xs rounded-lg px-3 py-2 ${available != null && parseFloat(form.amount || 0) > available + 0.01
              ? 'bg-red-500/10 text-red-700 dark:text-red-300' : 'bg-foreground/5 text-foreground/70'}`} data-testid="wd-available">
              Saldo platform toko yang bisa ditarik: <b>{rp(available || 0)}</b>
              {selBal?.cash_code ? <> · masuk ke rekening <span className="font-mono">{selBal.cash_code}</span></> : <> · <span className="text-amber-600">rekening pencairan toko belum ditautkan</span></>}
              {available != null && parseFloat(form.amount || 0) > available + 0.01 ? ' — melebihi saldo; catat dulu laporan dana dilepas yang belum masuk.' : ''}
            </div>
          ) : null}
          <div className="flex gap-2">
            <button data-testid="wd-save" disabled={busy === 'save'} onClick={save}
              className="h-9 px-4 rounded-lg bg-primary text-primary-foreground text-sm flex items-center gap-1.5 disabled:opacity-50">
              {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Simpan
            </button>
            <button data-testid="wd-cancel" onClick={() => setFormOpen(false)} className="h-9 px-4 rounded-lg bg-foreground/5 hover:bg-foreground/10 text-sm">Batal</button>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="py-6 text-center text-xs text-foreground/50 flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> memuat penarikan…</div>
      ) : rows.length === 0 ? (
        <div className="py-6 text-center text-xs text-foreground/50" data-testid="wd-empty">Belum ada penarikan saldo tercatat.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="wd-table">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-foreground/50 border-b border-foreground/10">
                <th className="text-left py-2 px-3">Tanggal</th>
                <th className="text-left py-2 px-3">No. Penarikan</th>
                <th className="text-left py-2 px-3">Toko</th>
                <th className="text-right py-2 px-3">Nominal</th>
                <th className="text-left py-2 px-3">Bank</th>
                <th className="text-left py-2 px-3">Jurnal</th>
                <th className="text-right py-2 px-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-foreground/5" data-testid={`wd-row-${r.reference}`}>
                  <td className="py-2 px-3">{r.withdrawal_date}</td>
                  <td className="py-2 px-3 font-mono text-xs">{r.reference}</td>
                  <td className="py-2 px-3">{accName(r.account_id)} <span className="text-xs text-foreground/50 uppercase">{r.platform}</span></td>
                  <td className="py-2 px-3 text-right tabular-nums font-medium">{rp(r.amount)}</td>
                  <td className="py-2 px-3 text-[10px]">
                    {r.bank_txn_id
                      ? <span className="text-emerald-600 flex items-center gap-0.5"><Landmark className="w-3 h-3" /> mutasi {r.bank_txn_date}</span>
                      : <span className="text-foreground/40">belum tertaut</span>}
                  </td>
                  <td className="py-2 px-3 text-xs">
                    {r.je_number ? <span className="font-mono">{r.je_number} <span className="text-foreground/50">({r.je_status})</span></span>
                      : <span className="text-foreground/40">belum</span>}
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex items-center justify-end gap-1">
                      {!r.je_id ? (
                        <button title="Buat jurnal draf" data-testid={`wd-journal-${r.reference}`} disabled={busy === `journal:${r.id}`}
                          onClick={() => act(r, 'journal')} className="p-1.5 rounded hover:bg-foreground/10 disabled:opacity-40"><BookCheck className="w-4 h-4" /></button>
                      ) : null}
                      {r.je_status === 'draft' ? (
                        <button title="Posting jurnal" data-testid={`wd-post-${r.reference}`} disabled={busy === `post:${r.id}`}
                          onClick={() => act(r, 'post')} className="p-1.5 rounded hover:bg-foreground/10 text-emerald-600 disabled:opacity-40"><Send className="w-4 h-4" /></button>
                      ) : null}
                      {!r.je_id ? (
                        <>
                          <button title="Koreksi" data-testid={`wd-edit-${r.reference}`} onClick={() => openEdit(r)} className="p-1.5 rounded hover:bg-foreground/10"><Pencil className="w-4 h-4" /></button>
                          {!r.bank_txn_id ? (
                            <button title="Hapus" data-testid={`wd-delete-${r.reference}`} disabled={busy === `delete:${r.id}`}
                              onClick={() => act(r, 'delete')} className="p-1.5 rounded hover:bg-foreground/10 text-red-600 disabled:opacity-40"><Trash2 className="w-4 h-4" /></button>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  );
}
