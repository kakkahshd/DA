import { useEffect, useMemo, useState } from 'react';
import { ReceiptText, Plus, RefreshCw, Trash2, Printer, CheckCircle2, Eye, Wallet, XCircle, AlertTriangle, Undo2 } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import Modal from '../Modal';
import { PageHeader } from '../moduleAtoms';
import { apiGet, apiPost, apiFetch } from '../../../lib/api';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
const today = () => new Date().toISOString().slice(0, 10);
const STATUS = { draft: ['Draft', 'text-amber-300 bg-amber-400/10 border-amber-400/25'], confirmed: ['Belum Lunas', 'text-sky-300 bg-sky-400/10 border-sky-400/25'], paid: ['Lunas', 'text-emerald-300 bg-emerald-400/10 border-emerald-400/25'], cancelled: ['Batal', 'text-red-300 bg-red-400/10 border-red-400/25'], confirming: ['Memproses', 'text-muted-foreground'] };
const sel = 'w-full h-9 rounded-md border border-[var(--glass-border)] bg-transparent px-2 text-sm';

function Badge({ s }) { const [l, c] = STATUS[s] || [s, '']; return <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded border ${c}`} data-testid={`sale-status-${s}`}>{l}</span>; }

async function openPdf(id, number) {
  const r = await apiFetch(`/sales/direct-sales/${id}/pdf`);
  if (!r.ok) return toast.error('Gagal membuat PDF');
  const url = URL.createObjectURL(await r.blob());
  window.open(url, '_blank') || (() => { const a = document.createElement('a'); a.href = url; a.download = `Nota_${number}.pdf`; a.click(); })();
}

export default function DirectSalesModule() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = async () => { try { setRows(await apiGet(`/sales/direct-sales${filter ? `?status=${filter}` : ''}`)); } catch (e) { toast.error(e.message); } };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = async (id) => { try { setDetail(await apiGet(`/sales/direct-sales/${id}`)); } catch (e) { toast.error(e.message); } };

  return (
    <div className="space-y-5" data-testid="direct-sales-page">
      <PageHeader icon={ReceiptText} eyebrow="Portal Penjualan" title="Nota Penjualan Langsung" subtitle="Draft → Konfirmasi: stok FG keluar (FIFO), HPP dibukukan, invoice piutang terbit; tunai langsung lunas ke kas."
        actions={<>
          <Button variant="ghost" onClick={load} className="h-9 border border-[var(--glass-border)]" data-testid="sales-refresh"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat Ulang</Button>
          <Button onClick={() => setCreating(true)} className="h-9" data-testid="sales-new"><Plus className="w-3.5 h-3.5 mr-1.5" />Nota Baru</Button>
        </>} />
      <GlassCard className="p-3 flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">Status</span>
        <select className={`${sel} w-44`} value={filter} onChange={e => setFilter(e.target.value)} data-testid="sales-filter"><option value="">Semua</option><option value="draft">Draft</option><option value="confirmed">Belum Lunas</option><option value="paid">Lunas</option><option value="cancelled">Batal</option></select>
      </GlassCard>
      <GlassCard className="p-0 overflow-hidden">
        {!rows.length ? <div className="py-14 text-center text-sm text-muted-foreground" data-testid="sales-empty">Belum ada nota penjualan.</div> : (
          <table className="w-full text-xs" data-testid="sales-table">
            <thead className="bg-foreground/5 text-muted-foreground"><tr>
              <th className="text-left px-3 py-2">No. Nota</th><th className="text-left px-3 py-2">Tanggal</th><th className="text-left px-3 py-2">Pelanggan</th><th className="text-left px-3 py-2">Bayar</th><th className="text-right px-3 py-2">Total</th><th className="text-right px-3 py-2">HPP</th><th className="text-left px-3 py-2">Status</th><th className="px-3 py-2" />
            </tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.id} className="border-t border-foreground/5" data-testid={`sale-row-${r.note_number}`}>
                <td className="px-3 py-2 font-mono">{r.note_number}{r.invoice_number && <div className="text-muted-foreground">{r.invoice_number}</div>}</td>
                <td className="px-3 py-2">{r.sale_date}</td>
                <td className="px-3 py-2">{r.customer_name}</td>
                <td className="px-3 py-2">{r.payment_type === 'cash' ? 'Tunai' : `Tempo · JT ${r.due_date}`}</td>
                <td className="px-3 py-2 text-right font-semibold">Rp {fmt(r.total)}</td>
                <td className="px-3 py-2 text-right">{r.cogs_total != null ? `Rp ${fmt(r.cogs_total)}` : '-'}{r.cogs_basis && r.cogs_basis !== 'fifo_batch' && <div className="text-[10px] text-amber-300">{r.cogs_basis === 'hpp_master' ? 'perkiraan HPP master' : 'sebagian perkiraan'}</div>}{r.uncosted_qty > 0 && !r.cogs_estimated && <div className="text-[10px] text-amber-300">{r.uncosted_qty} pcs tanpa biaya</div>}</td>
                <td className="px-3 py-2"><Badge s={r.status} /></td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <Button size="sm" variant="ghost" onClick={() => openDetail(r.id)} data-testid={`sale-view-${r.note_number}`}><Eye className="w-3.5 h-3.5" /></Button>
                  <Button size="sm" variant="ghost" onClick={() => openPdf(r.id, r.note_number)} data-testid={`sale-pdf-${r.note_number}`}><Printer className="w-3.5 h-3.5" /></Button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </GlassCard>
      {creating && <CreateSaleModal onClose={() => setCreating(false)} onSaved={(n) => { setCreating(false); load(); openDetail(n.id); }} />}
      {detail && <SaleDetailModal note={detail} onClose={() => setDetail(null)} onChanged={(n) => { setDetail(n); load(); }} />}
    </div>
  );
}

function CreateSaleModal({ onClose, onSaved }) {
  const [customers, setCustomers] = useState([]);
  const [stock, setStock] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [f, setF] = useState({ customer_id: '', payment_type: 'cash', cash_account_id: '', sale_date: today(), due_date: '', tax_pct: 0, discount_amount: 0, notes: '' });
  const [items, setItems] = useState([{ material_id: '', qty: 1, price: 0 }]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    Promise.all([apiGet('/sales/customers'), apiGet('/sales/fg-stock'), apiGet('/sales/cash-accounts')])
      .then(([c, s, a]) => { setCustomers(c); setStock(s); setAccounts(a); if (a[0]) setF(x => ({ ...x, cash_account_id: a[0].id })); })
      .catch(e => toast.error(e.message));
  }, []);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const setItem = (i, k, v) => setItems(arr => arr.map((it, idx) => {
    if (idx !== i) return it;
    const n = { ...it, [k]: v };
    if (k === 'material_id') { const s = stock.find(x => x.material_id === v); n.price = s?.default_price || n.price || 0; }
    return n;
  }));
    const subtotal = items.reduce((s, it) => s + (Number(it.qty) || 0) * (Number(it.price) || 0), 0);
  const disc = Number(f.discount_amount) || 0;
  const tax = Math.round((subtotal - disc) * (Number(f.tax_pct) || 0) / 100);
  const total = subtotal - disc + tax;
  const cust = customers.find(c => c.id === f.customer_id);

  const submit = async () => {
    if (!f.customer_id) return toast.error('Pilih pelanggan.');
    const clean = items.filter(it => it.material_id);
    if (!clean.length) return toast.error('Tambahkan minimal satu item.');
    setBusy(true);
    try {
      const n = await apiPost('/sales/direct-sales', { ...f, items: clean, due_date: f.due_date || undefined });
      toast.success(`Draft ${n.note_number} tersimpan`); onSaved(n);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Nota Penjualan Baru" onClose={onClose} size="2xl">
      <div className="space-y-4 text-sm" data-testid="sale-form">
        <div className="grid md:grid-cols-3 gap-3">
          <label className="space-y-1 md:col-span-1"><span className="text-xs text-muted-foreground">Pelanggan *</span>
            <select className={sel} value={f.customer_id} onChange={e => set('customer_id', e.target.value)} data-testid="sale-form-customer"><option value="">— pilih —</option>{customers.map(c => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}</select>
            {cust && <div className="text-[11px] text-muted-foreground">Termin: {cust.payment_terms}</div>}</label>
          <label className="space-y-1"><span className="text-xs text-muted-foreground">Tanggal</span><GlassInput type="date" value={f.sale_date} onChange={e => set('sale_date', e.target.value)} data-testid="sale-form-date" /></label>
          <label className="space-y-1"><span className="text-xs text-muted-foreground">Pembayaran</span>
            <select className={sel} value={f.payment_type} onChange={e => set('payment_type', e.target.value)} data-testid="sale-form-payment"><option value="cash">Tunai (langsung lunas)</option><option value="credit">Tempo (piutang)</option></select></label>
          {f.payment_type === 'cash' ? (
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Masuk ke Kas/Bank *</span>
              <select className={sel} value={f.cash_account_id} onChange={e => set('cash_account_id', e.target.value)} data-testid="sale-form-cash-account">{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          ) : (
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Jatuh Tempo (kosong = termin pelanggan)</span><GlassInput type="date" value={f.due_date} onChange={e => set('due_date', e.target.value)} data-testid="sale-form-due" /></label>
          )}
          <label className="space-y-1"><span className="text-xs text-muted-foreground">PPN</span>
            <select className={sel} value={f.tax_pct} onChange={e => set('tax_pct', Number(e.target.value))} data-testid="sale-form-tax"><option value={0}>Tanpa PPN</option><option value={11}>PPN 11%</option><option value={12}>PPN 12%</option></select></label>
          <label className="space-y-1"><span className="text-xs text-muted-foreground">Diskon (Rp)</span><GlassInput type="number" min="0" value={f.discount_amount} onChange={e => set('discount_amount', e.target.value)} data-testid="sale-form-discount" /></label>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between"><span className="text-xs font-semibold">Item (stok FG tersedia: {stock.length} SKU)</span><Button size="sm" variant="ghost" onClick={() => setItems(a => [...a, { material_id: '', qty: 1, price: 0 }])} data-testid="sale-form-add-item"><Plus className="w-3.5 h-3.5 mr-1" />Tambah baris</Button></div>
          <table className="w-full text-xs"><thead className="text-muted-foreground"><tr><th className="text-left py-1">SKU</th><th className="w-20 text-right">Stok</th><th className="w-20">Qty</th><th className="w-32">Harga</th><th className="w-28 text-right">Jumlah</th><th className="w-8" /></tr></thead>
            <tbody>{items.map((it, i) => { const s = stock.find(x => x.material_id === it.material_id); return (
              <tr key={i} className="border-t border-foreground/5">
                <td className="py-1 pr-2"><select className={sel} value={it.material_id} onChange={e => setItem(i, 'material_id', e.target.value)} data-testid={`sale-item-${i}-sku`}><option value="">— pilih SKU —</option>{stock.map(x => <option key={x.material_id} value={x.material_id}>{x.sku} · {x.name} (stok {x.available_qty})</option>)}</select></td>
                <td className="text-right">{s ? s.available_qty : '-'}{s?.hpp > 0 && <div className="text-[10px] text-muted-foreground">HPP {fmt(s.hpp)}</div>}</td>
                <td><GlassInput type="number" min="1" value={it.qty} onChange={e => setItem(i, 'qty', e.target.value)} className="h-8" data-testid={`sale-item-${i}-qty`} /></td>
                <td><GlassInput type="number" min="0" value={it.price} onChange={e => setItem(i, 'price', e.target.value)} className="h-8" data-testid={`sale-item-${i}-price`} /></td>
                <td className="text-right font-semibold">{fmt((Number(it.qty) || 0) * (Number(it.price) || 0))}</td>
                <td><Button size="sm" variant="ghost" onClick={() => setItems(a => a.filter((_, idx) => idx !== i))}><Trash2 className="w-3.5 h-3.5 text-red-400" /></Button></td>
              </tr>); })}</tbody></table>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="space-y-1 flex-1 min-w-[200px]"><span className="text-xs text-muted-foreground">Catatan</span><GlassInput value={f.notes} onChange={e => set('notes', e.target.value)} data-testid="sale-form-notes" /></label>
          <div className="text-right text-xs space-y-0.5" data-testid="sale-form-totals">
            <div>Subtotal <b>Rp {fmt(subtotal)}</b></div>
            {tax > 0 && <div>PPN {f.tax_pct}% <b>Rp {fmt(tax)}</b></div>}
            {Number(f.discount_amount) > 0 && <div>Diskon <b>- Rp {fmt(f.discount_amount)}</b></div>}
            <div className="text-base">Total <b>Rp {fmt(total)}</b></div>
          </div>
        </div>
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Batal</Button><Button onClick={submit} disabled={busy} data-testid="sale-form-save">Simpan Draft</Button></div>
      </div>
    </Modal>
  );
}

function SaleDetailModal({ note, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [pay, setPay] = useState(null);
  const [ret, setRet] = useState(null);
  const [accounts, setAccounts] = useState([]);
  useEffect(() => { apiGet('/sales/cash-accounts').then(setAccounts).catch(() => {}); }, []);
  const inv = note.invoice;
  const balance = inv ? Number(inv.balance || 0) : 0;
  const returnedQty = (mid) => (note.returns || []).reduce((s, r) => s + r.items.filter(i => i.material_id === mid).reduce((a, i) => a + i.qty, 0), 0);
  const canReturn = ['confirmed', 'paid'].includes(note.status) && note.items.some(it => it.qty - returnedQty(it.material_id) > 0);
  const act = async (fn, ok) => { setBusy(true); try { const n = await fn(); toast.success(ok); onChanged(n.note || n); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };
  const confirm = () => window.confirm(`Konfirmasi ${note.note_number}? Stok FG akan dikurangi dan jurnal dibuat.`) && act(() => apiPost(`/sales/direct-sales/${note.id}/confirm`, {}), 'Nota dikonfirmasi');
  const cancel = () => window.confirm('Batalkan draft ini?') && act(() => apiPost(`/sales/direct-sales/${note.id}/cancel`, {}), 'Draft dibatalkan');
  const doPay = () => act(async () => { await apiPost(`/sales/direct-sales/${note.id}/payment`, pay); setPay(null); return apiGet(`/sales/direct-sales/${note.id}`); }, 'Pembayaran dicatat');
  const openReturn = () => setRet({ items: note.items.map(it => ({ material_id: it.material_id, sku: it.sku, max: it.qty - returnedQty(it.material_id), qty: 0, condition: 'good' })), reason: '', refund_method: balance > 0 ? 'credit' : 'cash', cash_account_id: accounts[0]?.id || '' });
  const doReturn = () => {
    const items = ret.items.filter(i => Number(i.qty) > 0).map(i => ({ material_id: i.material_id, qty: Number(i.qty), condition: i.condition }));
    if (!items.length) return toast.error('Isi qty retur minimal satu item.');
    if (!window.confirm('Proses retur? Stok kembali, nota kredit & jurnal balik dibuat.')) return;
    act(async () => { const r = await apiPost(`/sales/direct-sales/${note.id}/returns`, { ...ret, items }); setRet(null); toast.info(`Nota kredit ${r.cn_number}${r.refund_amount ? ` · refund Rp ${fmt(r.refund_amount)}` : ''}${r.customer_credit ? ` · saldo kredit pelanggan Rp ${fmt(r.customer_credit)}` : ''}`); return apiGet(`/sales/direct-sales/${note.id}`); }, 'Retur diproses');
  };
  const gl = useMemo(() => [
    inv?.gl_je_number && `Invoice: ${inv.gl_je_number}`, note.cogs_je_number && `HPP: ${note.cogs_je_number}`,
    note.cogs_post_error && `HPP gagal: ${note.cogs_post_error}`, note.ar_post_error && `Invoice gagal: ${note.ar_post_error}`, note.payment_error && `Kas gagal: ${note.payment_error}`,
  ].filter(Boolean), [inv, note]);

  return (
    <Modal title={`Nota ${note.note_number}`} onClose={onClose} size="xl">
      <div className="space-y-4 text-sm" data-testid="sale-detail">
        <div className="flex flex-wrap items-center gap-3">
          <Badge s={note.status} />
          <span className="text-xs text-muted-foreground">{note.sale_date} · {note.customer_name} · {note.payment_type === 'cash' ? 'Tunai' : `Tempo, JT ${note.due_date}`}</span>
          {note.invoice_number && <span className="text-xs font-mono">Invoice {note.invoice_number}</span>}
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => openPdf(note.id, note.note_number)} data-testid="sale-detail-pdf"><Printer className="w-3.5 h-3.5 mr-1" />Cetak Nota</Button>
            {note.status === 'draft' && <Button size="sm" variant="ghost" onClick={cancel} disabled={busy} data-testid="sale-detail-cancel"><XCircle className="w-3.5 h-3.5 mr-1 text-red-400" />Batalkan</Button>}
            {note.status === 'draft' && <Button size="sm" onClick={confirm} disabled={busy} data-testid="sale-detail-confirm"><CheckCircle2 className="w-3.5 h-3.5 mr-1" />Konfirmasi</Button>}
            {note.status === 'confirmed' && balance > 0 && <Button size="sm" onClick={() => setPay({ amount: balance, cash_account_id: accounts[0]?.id || '', date: today() })} disabled={busy} data-testid="sale-detail-pay"><Wallet className="w-3.5 h-3.5 mr-1" />Terima Pembayaran</Button>}
            {canReturn && <Button size="sm" variant="ghost" onClick={openReturn} disabled={busy} data-testid="sale-detail-return"><Undo2 className="w-3.5 h-3.5 mr-1 text-amber-400" />Retur</Button>}
          </div>
        </div>
        <table className="w-full text-xs" data-testid="sale-detail-items"><thead className="bg-foreground/5 text-muted-foreground"><tr><th className="text-left px-2 py-1">SKU</th><th className="text-right px-2">Qty</th><th className="text-right px-2">Harga</th><th className="text-right px-2">Jumlah</th><th className="text-right px-2">HPP FIFO</th></tr></thead>
          <tbody>{note.items.map((it, i) => <tr key={i} className="border-t border-foreground/5"><td className="px-2 py-1"><span className="font-mono">{it.sku}</span> <span className="text-muted-foreground">{it.name}</span></td><td className="text-right px-2">{it.qty}</td><td className="text-right px-2">{fmt(it.price)}</td><td className="text-right px-2 font-semibold">{fmt(it.amount)}</td><td className="text-right px-2">{it.fg_cogs != null ? fmt(it.fg_cogs) : '-'}{it.fg_cogs_estimated > 0 && <div className="text-[10px] text-amber-300">+ {fmt(it.fg_cogs_estimated)} perkiraan HPP master ({it.fg_cogs_uncosted_qty} pcs)</div>}{it.fg_cogs_uncosted_qty > 0 && !it.fg_cogs_estimated && <div className="text-[10px] text-amber-300">{it.fg_cogs_uncosted_qty} tanpa biaya</div>}</td></tr>)}</tbody></table>
        <div className="flex flex-wrap justify-between gap-3 text-xs">
          <div className="space-y-1">
            {gl.map((g, i) => <div key={i} className={`font-mono ${g.includes('gagal') ? 'text-red-300' : 'text-muted-foreground'}`} data-testid="sale-detail-gl">{g}</div>)}
            {note.uncosted_qty > 0 && !note.cogs_estimated && <div className="flex items-center gap-1 text-amber-300"><AlertTriangle className="w-3.5 h-3.5" />{note.uncosted_qty} pcs keluar tanpa lapisan biaya — HPP lebih rendah dari kenyataan.</div>}
            {note.cogs_estimated > 0 && <div className="flex items-center gap-1 text-amber-300"><AlertTriangle className="w-3.5 h-3.5" />Rp {fmt(note.cogs_estimated)} HPP memakai perkiraan HPP master ({note.uncosted_qty} pcs tanpa lapisan biaya batch).</div>}
            {inv && <div>Piutang: dibayar Rp {fmt(inv.paid_amount)} · sisa <b data-testid="sale-detail-balance">Rp {fmt(inv.balance)}</b> · status invoice {inv.status}</div>}
          </div>
          <div className="text-right space-y-0.5"><div>Subtotal Rp {fmt(note.subtotal)}</div>{note.tax_amount > 0 && <div>PPN {note.tax_pct}% Rp {fmt(note.tax_amount)}</div>}{note.discount_amount > 0 && <div>Diskon - Rp {fmt(note.discount_amount)}</div>}<div className="text-base">Total <b>Rp {fmt(note.total)}</b></div>{note.cogs_total != null && <div className="text-muted-foreground">HPP Rp {fmt(note.cogs_total)} · Laba kotor Rp {fmt(note.subtotal - note.discount_amount - note.cogs_total)}</div>}</div>
        </div>
        {pay && (
          <GlassCard className="p-3 flex flex-wrap items-end gap-3" data-testid="sale-pay-form">
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Jumlah</span><GlassInput type="number" min="1" value={pay.amount} onChange={e => setPay(p => ({ ...p, amount: e.target.value }))} className="h-8 w-40" data-testid="sale-pay-amount" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Kas/Bank</span><select className={`${sel} h-8`} value={pay.cash_account_id} onChange={e => setPay(p => ({ ...p, cash_account_id: e.target.value }))} data-testid="sale-pay-account">{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Tanggal</span><GlassInput type="date" value={pay.date} onChange={e => setPay(p => ({ ...p, date: e.target.value }))} className="h-8" /></label>
            <Button size="sm" onClick={doPay} disabled={busy} data-testid="sale-pay-submit">Simpan Pembayaran</Button>
            <Button size="sm" variant="ghost" onClick={() => setPay(null)}>Batal</Button>
          </GlassCard>
        )}
        {ret && (
          <GlassCard className="p-3 space-y-2" data-testid="sale-return-form">
            <div className="text-xs font-semibold">Retur Penjualan — pilih qty per item</div>
            <table className="w-full text-xs"><thead className="text-muted-foreground"><tr><th className="text-left py-1">SKU</th><th className="text-right">Bisa diretur</th><th className="w-24">Qty Retur</th><th className="w-44">Kondisi</th></tr></thead>
              <tbody>{ret.items.map((it, i) => (
                <tr key={it.material_id} className="border-t border-foreground/5"><td className="py-1 font-mono">{it.sku}</td><td className="text-right">{it.max}</td>
                  <td><GlassInput type="number" min="0" max={it.max} value={it.qty} disabled={it.max <= 0} onChange={e => setRet(r => ({ ...r, items: r.items.map((x, idx) => idx === i ? { ...x, qty: e.target.value } : x) }))} className="h-8" data-testid={`sale-return-qty-${i}`} /></td>
                  <td><select className={`${sel} h-8`} value={it.condition} onChange={e => setRet(r => ({ ...r, items: r.items.map((x, idx) => idx === i ? { ...x, condition: e.target.value } : x) }))} data-testid={`sale-return-cond-${i}`}><option value="good">Baik (kembali ke stok)</option><option value="damaged">Rusak (tidak ke stok)</option></select></td></tr>
              ))}</tbody></table>
            <div className="flex flex-wrap items-end gap-3">
              <label className="space-y-1 flex-1 min-w-[180px]"><span className="text-xs text-muted-foreground">Alasan</span><GlassInput value={ret.reason} onChange={e => setRet(r => ({ ...r, reason: e.target.value }))} className="h-8" data-testid="sale-return-reason" /></label>
              <label className="space-y-1"><span className="text-xs text-muted-foreground">Kelebihan kredit</span>
                <select className={`${sel} h-8`} value={ret.refund_method} onChange={e => setRet(r => ({ ...r, refund_method: e.target.value }))} data-testid="sale-return-refund"><option value="credit">Potong tagihan / simpan sbg kredit pelanggan</option><option value="cash">Refund tunai dari kas</option></select></label>
              {ret.refund_method === 'cash' && <label className="space-y-1"><span className="text-xs text-muted-foreground">Kas/Bank</span><select className={`${sel} h-8`} value={ret.cash_account_id} onChange={e => setRet(r => ({ ...r, cash_account_id: e.target.value }))} data-testid="sale-return-account">{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
              <Button size="sm" onClick={doReturn} disabled={busy} data-testid="sale-return-submit">Proses Retur</Button>
              <Button size="sm" variant="ghost" onClick={() => setRet(null)}>Batal</Button>
            </div>
          </GlassCard>
        )}
        {note.returns?.length > 0 && (
          <div className="space-y-1" data-testid="sale-returns-list">
            <div className="text-xs font-semibold">Riwayat Retur</div>
            {note.returns.map(r => (
              <div key={r.id} className="text-xs flex flex-wrap gap-x-3 border-t border-foreground/5 py-1" data-testid={`sale-return-row-${r.return_number}`}>
                <span className="font-mono">{r.return_number}</span><span>{r.return_date}</span><span>{r.items.map(i => `${i.sku} ×${i.qty}`).join(', ')}</span>
                <span className="font-semibold">Kredit Rp {fmt(r.total)}</span><span className="text-muted-foreground">CN {r.cn_number}{r.cn_je_number ? ` · ${r.cn_je_number}` : ''}{r.cogs_je_number ? ` · HPP ${r.cogs_je_number}` : ''}</span>
                {r.refund_amount > 0 && <span className="text-emerald-300">refund Rp {fmt(r.refund_amount)}</span>}{r.customer_credit > 0 && <span className="text-amber-300">kredit pelanggan Rp {fmt(r.customer_credit)}</span>}
                {r.reason && <span className="text-muted-foreground">“{r.reason}”</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
