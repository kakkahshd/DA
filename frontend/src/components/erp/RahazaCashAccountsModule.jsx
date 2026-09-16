import { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, Edit2, Trash2, Wallet, BookOpen, AlertTriangle } from 'lucide-react';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { formatRupiah } from '@/lib/format';
import { toast } from 'sonner';

const fmt = formatRupiah;

export default function RahazaCashAccountsModule({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [movements, setMovements] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/cash-accounts', { headers });
      if (r.ok) setAccounts(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);

  const syncGl = async () => {
    setSyncing(true);
    try {
      const r = await fetch('/api/rahaza/cash-accounts/sync-gl', { method: 'POST', headers });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast.error(d.detail || `Gagal sinkron GL (HTTP ${r.status})`); return; }
      const posted = (d.report || []).filter(x => x.opening).length;
      const failed = (d.report || []).filter(x => x.error).length;
      const created = (d.sync?.cash_accounts_created || []).length;
      toast[failed ? 'warning' : 'success'](`Sinkron selesai · ${created} rekening baru dari Bagan Akun · ${posted} jurnal saldo awal · ${failed} gagal`);
      setAccounts(d.accounts || []);
    } finally { setSyncing(false); }
  };

  const fetchMovements = async (account_id) => {
    const r = await fetch(`/api/rahaza/cash-movements?account_id=${account_id}`, { headers });
    if (r.ok) setMovements(await r.json());
  };

  const save = async (body) => {
    const url = body.id ? `/api/rahaza/cash-accounts/${body.id}` : '/api/rahaza/cash-accounts';
    const method = body.id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers, body: JSON.stringify(body) });
    if (r.ok) {
      const d = await r.json().catch(() => ({}));
      if (d._opening_post && d._opening_post.je_number) toast.success(`Rekening dibuat · saldo awal dijurnal ${d._opening_post.je_number}`);
      else if (d._opening_post && d._opening_post.error) toast.error(`Rekening dibuat, tetapi jurnal saldo awal GAGAL: ${d._opening_post.error}`);
      setEditing(null); fetchAccounts();
    }
  };
  const del = async (id) => { if (!window.confirm('Nonaktifkan rekening?')) return; await fetch(`/api/rahaza/cash-accounts/${id}`, { method: 'DELETE', headers }); fetchAccounts(); };

  const total = accounts.reduce((s, a) => s + (Number(a.balance) || 0), 0);
  const mismatch = accounts.filter(a => a.balance_source === 'gl' && a.balance_diff !== 0);
  const noGl = accounts.filter(a => a.balance_source !== 'gl');

  return (
    <div className="space-y-5" data-testid="rahaza-cash-page">
      <PageHeader
        icon={Wallet}
        eyebrow="Portal Finance · Rahaza Finance"
        title="Cash & Bank Accounts"
        subtitle="Saldo kartu dibaca langsung dari Buku Besar (akun GL rekening) sehingga kas, GL, dan mutasi bank selalu satu angka."
        actions={
          <>
            <Button variant="ghost" onClick={syncGl} disabled={syncing} className="h-9 border border-[var(--glass-border)]" data-testid="ca-sync-gl"><BookOpen className="w-3.5 h-3.5 mr-1.5" />{syncing ? 'Sinkron…' : 'Sinkron Bagan Akun & GL'}</Button>
            <Button variant="ghost" onClick={fetchAccounts} className="h-9 border border-[var(--glass-border)]"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
            <Button onClick={() => setEditing({ code: '', name: '', type: 'cash', opening_balance: 0 })} className="h-9" data-testid="ca-add"><Plus className="w-3.5 h-3.5 mr-1.5" />Tambah</Button>
          </>
        }
      />
      <StatTile label="Total Saldo Semua Rekening (Buku Besar)" value={fmt(total)} accent="success" className="md:col-span-3" testId="ca-total-gl" />
      {(mismatch.length > 0 || noGl.length > 0) && (
        <div className="bg-amber-400/8 border border-amber-400/20 rounded-lg px-4 py-3 text-xs text-amber-300 flex items-start gap-2" data-testid="ca-gl-warning">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            {mismatch.length > 0 && <p>{mismatch.length} rekening saldo GL ≠ saldo mutasi ({mismatch.map(a => a.code).join(', ')}). Angka kartu memakai GL; selisih berarti ada mutasi yang belum dijurnal.</p>}
            {noGl.length > 0 && <p>{noGl.length} rekening belum punya akun GL ({noGl.map(a => a.code).join(', ')}) — tekan “Sinkron GL”.</p>}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {accounts.map(a => (
          <GlassCard key={a.id} className="p-4 cursor-pointer" onClick={() => { setSelected(a); fetchMovements(a.id); }} data-testid={`ca-card-${a.code}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="font-mono text-xs text-muted-foreground">{a.code}{a.gl_account_code && <span className="ml-2 text-primary/80">GL {a.gl_account_code}</span>}</div>
                <div className="font-semibold text-foreground">{a.name}</div>
                <div className="text-[10px] uppercase text-muted-foreground mt-1">{a.type} {a.bank_name && `· ${a.bank_name}`}</div>
              </div>
              <div className="flex gap-1"><button onClick={e => { e.stopPropagation(); setEditing({...a}); }} className="text-primary hover:bg-primary/10 rounded p-1"><Edit2 className="w-3 h-3" /></button><button onClick={e => { e.stopPropagation(); del(a.id); }} className="text-red-300 hover:bg-red-400/10 rounded p-1"><Trash2 className="w-3 h-3" /></button></div>
            </div>
            <div className="mt-3 text-2xl font-bold text-foreground" data-testid={`ca-balance-${a.code}`}>{fmt(a.balance)}</div>
            <div className="mt-1 flex items-center justify-between text-[10px]">
              <span className={a.balance_source === 'gl' ? 'text-emerald-400' : 'text-amber-400'} data-testid={`ca-source-${a.code}`}>
                {a.balance_source === 'gl' ? 'Saldo Buku Besar' : 'Belum tertaut GL · saldo dari mutasi'}
              </span>
              {a.balance_source === 'gl' && (
                <span className={a.balance_diff === 0 ? 'text-muted-foreground' : 'text-amber-400'} data-testid={`ca-diff-${a.code}`}>
                  Mutasi {fmt(a.balance_mutasi)}{a.balance_diff !== 0 && ` · selisih ${fmt(a.balance_diff)}`}
                </span>
              )}
            </div>
          </GlassCard>
        ))}
        {accounts.length === 0 && !loading && <GlassCard className="p-6 text-center text-muted-foreground col-span-full">Belum ada rekening. Tekan “Tambah”.</GlassCard>}
      </div>
      {selected && (
        <GlassCard className="p-4" data-testid="ca-movements-panel">
          <div className="flex items-center justify-between mb-3"><h3 className="font-semibold text-foreground">Mutasi: {selected.code} · {selected.name}</h3><button onClick={() => setSelected(null)} className="text-muted-foreground">×</button></div>
          {movements.length === 0 ? <div className="text-xs text-muted-foreground text-center py-8">Belum ada mutasi.</div> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted-foreground"><th className="pb-2">Tanggal</th><th className="pb-2">Kategori</th><th className="pb-2">Ref</th><th className="pb-2 text-right">Masuk</th><th className="pb-2 text-right">Keluar</th></tr></thead>
              <tbody>{movements.map(m => (<tr key={m.id} className="border-t border-[var(--glass-border)]"><td className="py-2 text-xs">{m.date}</td><td className="py-2 text-xs">{m.category}</td><td className="py-2 text-xs font-mono">{m.ref_label || '-'}</td><td className="py-2 text-right font-mono text-emerald-300 text-xs">{m.direction === 'in' ? fmt(m.amount) : ''}</td><td className="py-2 text-right font-mono text-red-300 text-xs">{m.direction === 'out' ? fmt(m.amount) : ''}</td></tr>))}</tbody>
            </table>
          )}
        </GlassCard>
      )}
      {editing && <CAEditor value={editing} onClose={() => setEditing(null)} onSave={save} headers={headers} />}
    </div>
  );
}

function CAEditor({ value, onClose, onSave, headers }) {
  const [s, setS] = useState(value);
  const [glOptions, setGlOptions] = useState([]);
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  useEffect(() => {
    if (s.id) return;
    fetch('/api/rahaza/cash-accounts/gl-candidates', { headers }).then(r => (r.ok ? r.json() : [])).then(setGlOptions).catch(() => setGlOptions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const pickGl = (code) => {
    const o = glOptions.find(x => x.code === code);
    setS(x => ({ ...x, gl_account_code: code, code: o ? code : x.code, name: o && !x.name ? o.name : x.name, type: o ? (code.startsWith('1-11') ? 'cash' : 'bank') : x.type }));
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-md w-full" onClick={e => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-foreground mb-4">{s.id ? 'Edit' : 'Tambah'} Rekening</h2>
        <div className="space-y-3">
          {!s.id && (
            <div>
              <label className="text-xs uppercase text-muted-foreground">Akun GL (Bagan Akun)</label>
              <select value={s.gl_account_code || ''} onChange={e => pickGl(e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground" data-testid="ca-gl-select">
                <option value="">— Buat akun GL baru otomatis di bawah Kas/Bank —</option>
                {glOptions.map(o => <option key={o.code} value={o.code}>{o.code} · {o.name}</option>)}
              </select>
              <p className="text-[11px] text-muted-foreground mt-1">{glOptions.length ? `${glOptions.length} akun kas/bank di Bagan Akun belum punya rekening — pilih supaya tidak dobel.` : 'Semua akun kas/bank di Bagan Akun sudah punya rekening.'}</p>
            </div>
          )}
          <div><label className="text-xs uppercase text-muted-foreground">Kode</label><GlassInput value={s.code} onChange={e => upd('code', e.target.value.toUpperCase())} disabled={!!s.id} data-testid="ca-code" /></div>
          <div><label className="text-xs uppercase text-muted-foreground">Nama</label><GlassInput value={s.name} onChange={e => upd('name', e.target.value)} data-testid="ca-name" /></div>
          <div><label className="text-xs uppercase text-muted-foreground">Tipe</label><select value={s.type} onChange={e => upd('type', e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"><option value="cash">Kas</option><option value="bank">Bank</option></select></div>
          {s.type === 'bank' && <>
            <div><label className="text-xs uppercase text-muted-foreground">Nama Bank</label><GlassInput value={s.bank_name || ''} onChange={e => upd('bank_name', e.target.value)} /></div>
            <div><label className="text-xs uppercase text-muted-foreground">Nomor Rekening</label><GlassInput value={s.account_number || ''} onChange={e => upd('account_number', e.target.value)} /></div>
          </>}
          {!s.id && <div><label className="text-xs uppercase text-muted-foreground">Saldo Awal</label><GlassInput type="number" min={0} value={s.opening_balance || 0} onChange={e => upd('opening_balance', Number(e.target.value))} /></div>}
        </div>
        <div className="flex gap-2 mt-6 justify-end"><Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Batal</Button><Button onClick={() => onSave(s)} data-testid="ca-save">Simpan</Button></div>
      </GlassCard>
    </div>
  );
}
