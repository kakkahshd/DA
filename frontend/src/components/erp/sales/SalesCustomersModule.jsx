import { useEffect, useMemo, useState } from 'react';
import { Contact, Plus, Pencil, Ban, RefreshCw, Search } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import Modal from '../Modal';
import { PageHeader } from '../moduleAtoms';
import { apiGet, apiPost, apiPut, apiDelete, getToken } from '../../../lib/api';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../docnum/DocNumberField';

export const TERMS = [
  { v: 'cash', l: 'Tunai' }, { v: 'net_7', l: 'Tempo 7 hari' }, { v: 'net_14', l: 'Tempo 14 hari' }, { v: 'net_30', l: 'Tempo 30 hari' },
];
const EMPTY = { code: '', name: '', company_type: 'personal', phone: '', email: '', npwp: '', address: '', payment_terms: 'cash', credit_limit: 0, notes: '' };

export default function SalesCustomersModule() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState('');
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const numPolicy = useDocNumberPolicy('rahaza_customers.code', getToken());

  const load = async () => { try { setRows(await apiGet('/sales/customers?include_inactive=true')); } catch (e) { toast.error(e.message); } };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => rows.filter(r => !q || `${r.code} ${r.name} ${r.phone}`.toLowerCase().includes(q.toLowerCase())), [rows, q]);

  const save = async () => {
    if (!form.name?.trim()) return toast.error('Nama pelanggan wajib.');
    setBusy(true);
    try {
      if (form.id) await apiPut(`/sales/customers/${form.id}`, form);
      else { const { code, ...rest } = form; await apiPost('/sales/customers', { ...rest, ...docNumberPayload(numPolicy, 'code', code) }); }
      toast.success('Pelanggan tersimpan'); setForm(null); load();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const deactivate = async (r) => {
    if (!window.confirm(`Nonaktifkan pelanggan ${r.name}?`)) return;
    try { await apiDelete(`/sales/customers/${r.id}`); toast.success('Dinonaktifkan'); load(); } catch (e) { toast.error(e.message); }
  };
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  return (
    <div className="space-y-5" data-testid="sales-customers">
      <PageHeader icon={Contact} eyebrow="Portal Penjualan · Master" title="Master Pelanggan" subtitle="Pelanggan penjualan langsung. Termin bayar menentukan jatuh tempo nota tempo; setiap pelanggan otomatis punya sub-akun piutang."
        actions={<>
          <Button variant="ghost" onClick={load} className="h-9 border border-[var(--glass-border)]" data-testid="cust-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
          <Button onClick={() => setForm({ ...EMPTY })} className="h-9" data-testid="cust-add"><Plus className="w-3.5 h-3.5 mr-1.5" />Pelanggan Baru</Button>
        </>} />
      <GlassCard className="p-3 flex items-center gap-2"><Search className="w-4 h-4 text-muted-foreground" /><GlassInput value={q} onChange={e => setQ(e.target.value)} placeholder="Cari kode / nama / telepon" className="h-8 flex-1" data-testid="cust-search" /></GlassCard>
      <GlassCard className="p-0 overflow-hidden">
        {!filtered.length ? <div className="py-14 text-center text-sm text-muted-foreground" data-testid="cust-empty">Belum ada pelanggan. Klik “Pelanggan Baru”.</div> : (
          <table className="w-full text-xs" data-testid="cust-table">
            <thead className="bg-foreground/5 text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">Kode</th><th className="text-left px-3 py-2">Nama</th><th className="text-left px-3 py-2">Kontak</th><th className="text-left px-3 py-2">Termin</th><th className="text-right px-3 py-2">Limit Kredit</th><th className="text-left px-3 py-2">Status</th><th className="px-3 py-2" />
            </tr></thead>
            <tbody>{filtered.map(r => (
              <tr key={r.id} className="border-t border-foreground/5" data-testid={`cust-row-${r.code}`}>
                <td className="px-3 py-2 font-mono">{r.code}</td>
                <td className="px-3 py-2"><div className="font-semibold">{r.name}</div><div className="text-muted-foreground">{r.company_type === 'company' ? 'Perusahaan' : 'Perorangan'}{r.npwp ? ` · NPWP ${r.npwp}` : ''}</div></td>
                <td className="px-3 py-2">{r.phone || '-'}<div className="text-muted-foreground">{r.email}</div></td>
                <td className="px-3 py-2">{TERMS.find(t => t.v === r.payment_terms)?.l || r.payment_terms}</td>
                <td className="px-3 py-2 text-right">{Number(r.credit_limit || 0).toLocaleString('id-ID')}</td>
                <td className="px-3 py-2">{r.active === false ? <span className="text-red-400">Nonaktif</span> : <span className="text-emerald-400">Aktif</span>}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <Button size="sm" variant="ghost" onClick={() => setForm({ ...EMPTY, ...r })} data-testid={`cust-edit-${r.code}`}><Pencil className="w-3.5 h-3.5" /></Button>
                  {r.active !== false && <Button size="sm" variant="ghost" onClick={() => deactivate(r)} data-testid={`cust-deactivate-${r.code}`}><Ban className="w-3.5 h-3.5 text-red-400" /></Button>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </GlassCard>

      {form && (
        <Modal title={form.id ? `Ubah Pelanggan ${form.code}` : 'Pelanggan Baru'} onClose={() => setForm(null)} size="lg">
          <div className="grid md:grid-cols-2 gap-3 text-sm" data-testid="cust-form">
            {form.id
              ? <label className="space-y-1"><span className="text-xs text-muted-foreground">Kode</span><GlassInput value={form.code || ''} disabled data-testid="cust-form-code" /></label>
              : <DocNumberField policy={numPolicy} value={form.code} onChange={v => set('code', v)} testId="cust-form-code" label="Kode Pelanggan" />}
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Nama *</span><GlassInput value={form.name} onChange={e => set('name', e.target.value)} data-testid="cust-form-name" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Jenis</span>
              <select className="w-full h-9 rounded-md border border-[var(--glass-border)] bg-transparent px-2" value={form.company_type} onChange={e => set('company_type', e.target.value)} data-testid="cust-form-type"><option value="personal">Perorangan</option><option value="company">Perusahaan</option></select></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Termin Bayar</span>
              <select className="w-full h-9 rounded-md border border-[var(--glass-border)] bg-transparent px-2" value={form.payment_terms} onChange={e => set('payment_terms', e.target.value)} data-testid="cust-form-terms">{TERMS.map(t => <option key={t.v} value={t.v}>{t.l}</option>)}</select></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Telepon</span><GlassInput value={form.phone || ''} onChange={e => set('phone', e.target.value)} data-testid="cust-form-phone" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Email</span><GlassInput value={form.email || ''} onChange={e => set('email', e.target.value)} data-testid="cust-form-email" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">NPWP</span><GlassInput value={form.npwp || ''} onChange={e => set('npwp', e.target.value)} data-testid="cust-form-npwp" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Limit Kredit (Rp)</span><GlassInput type="number" min="0" value={form.credit_limit ?? 0} onChange={e => set('credit_limit', e.target.value)} data-testid="cust-form-limit" /></label>
            <label className="space-y-1 md:col-span-2"><span className="text-xs text-muted-foreground">Alamat</span><GlassInput value={form.address || ''} onChange={e => set('address', e.target.value)} data-testid="cust-form-address" /></label>
            <label className="space-y-1 md:col-span-2"><span className="text-xs text-muted-foreground">Catatan</span><GlassInput value={form.notes || ''} onChange={e => set('notes', e.target.value)} data-testid="cust-form-notes" /></label>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="ghost" onClick={() => setForm(null)}>Batal</Button>
            <Button onClick={save} disabled={busy} data-testid="cust-form-save">Simpan</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
