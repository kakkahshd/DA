import { useEffect, useState } from 'react';
import { History, BookOpen, FileDown } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatRupiah } from '@/lib/format';
import { toast } from 'sonner';

async function downloadReceipt(token, kind, invoiceId, paymentId) {
  try {
    const r = await fetch(`/api/rahaza/${kind}-invoices/${invoiceId}/payments/${paymentId}/receipt.pdf`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = (r.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'Kwitansi.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast.error(`Gagal mengunduh kwitansi: ${e.message}`); }
}

// Riwayat pembayaran per invoice (AR/AP) + nomor jurnal — staf tak perlu buka Buku Jurnal.
export function PaymentHistoryList({ token, kind, invoiceId }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let x = false;
    setRows(null); setErr('');
    fetch(`/api/rahaza/${kind}-invoices/${invoiceId}/payments`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { if (!x) setRows(Array.isArray(d) ? d : []); })
      .catch(e => { if (!x) { setErr(e.message); setRows([]); } });
    return () => { x = true; };
  }, [token, kind, invoiceId]);

  if (rows === null) return <div className="space-y-2">{[0, 1].map(i => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>;
  if (err) return <div className="text-xs text-red-400" data-testid="payment-history-error">Gagal memuat riwayat: {err}</div>;
  if (rows.length === 0) return <div className="text-xs text-muted-foreground py-4 text-center" data-testid="payment-history-empty">Belum ada pembayaran tercatat.</div>;
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  return (
    <div className="overflow-x-auto" data-testid="payment-history-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-foreground/50">
            <th className="py-2 pr-2">Tanggal</th>
            <th className="py-2 pr-2">Rekening</th>
            <th className="py-2 pr-2">No. Jurnal</th>
            <th className="py-2 pr-2">Catatan</th>
            <th className="py-2 text-right">Jumlah</th>
            <th className="py-2 pl-2 text-right">Kwitansi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-t border-[var(--glass-border)]" data-testid={`payment-row-${r.id}`}>
              <td className="py-2 pr-2 text-xs">{r.date}</td>
              <td className="py-2 pr-2 text-xs">{r.account_code ? `${r.account_code} · ${r.account_name}` : <span className="text-muted-foreground">Tanpa rekening</span>}</td>
              <td className="py-2 pr-2 text-xs">
                {r.gl_je_number
                  ? <span className="inline-flex items-center gap-1 font-mono text-emerald-400" data-testid={`payment-je-${r.id}`}><BookOpen size={11} />{r.gl_je_number}</span>
                  : <span className="text-[10px] text-red-400" title={r.post_error || ''}>{r.post_error ? 'Jurnal gagal' : 'Belum dijurnal'}</span>}
              </td>
              <td className="py-2 pr-2 text-xs text-muted-foreground truncate max-w-[180px]" title={r.notes}>{r.notes || '—'}</td>
              <td className="py-2 text-right font-mono text-xs">{formatRupiah(r.amount)}</td>
              <td className="py-2 pl-2 text-right">
                <button
                  onClick={() => downloadReceipt(token, kind, invoiceId, r.id)}
                  className="inline-flex items-center gap-1 h-6 px-2 rounded border border-[var(--glass-border)] text-[10px] text-foreground/70 hover:bg-[var(--glass-bg-hover)] transition-colors"
                  data-testid={`payment-receipt-${r.id}`}
                  title="Unduh kwitansi PDF"
                >
                  <FileDown size={11} />PDF
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-[var(--glass-border)] font-semibold">
            <td colSpan={4} className="py-2 text-right text-xs">Total dibayar ({rows.length} pembayaran)</td>
            <td className="py-2 text-right font-mono text-xs" data-testid="payment-history-total">{formatRupiah(total)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default function PaymentHistoryModal({ token, kind, invoice, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-2xl w-full max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()} data-testid="payment-history-modal">
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-xl font-bold text-foreground flex items-center gap-2"><History className="w-5 h-5 text-primary" />Riwayat Pembayaran</h2>
          <button onClick={onClose} className="text-foreground/60 hover:text-foreground" data-testid="payment-history-close">✕</button>
        </div>
        <p className="text-xs text-muted-foreground mb-4">
          {invoice.invoice_number} · {invoice.customer_name || invoice.vendor_name || ''} · Total {formatRupiah(invoice.total)} · Sisa {formatRupiah(invoice.balance)}
        </p>
        <PaymentHistoryList token={token} kind={kind} invoiceId={invoice.id} />
        <div className="flex justify-end mt-5">
          <Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Tutup</Button>
        </div>
      </GlassCard>
    </div>
  );
}
