// Alat bersama laporan keuangan turunan buku besar (12 bulan · neraca lajur · arus kas · saldo awal).
export const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
export const fmtCell = (n) => (Number(n || 0) === 0 ? '' : fmt(n));
export const authHeaders = (token) => ({ Authorization: `Bearer ${token}` });

export async function downloadXlsx(url, token, fallbackName) {
  const r = await fetch(url, { headers: authHeaders(token) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const cd = r.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^"]+)"?/);
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = (m && m[1]) || fallbackName;
  a.click();
  URL.revokeObjectURL(href);
}

export function yearOptions(span = 5) {
  const y = new Date().getFullYear();
  return Array.from({ length: span + 1 }, (_, i) => y + 1 - i);
}

export function YearSelect({ value, onChange, testId }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-8 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-xs text-foreground"
      data-testid={testId}
    >
      {yearOptions().map((y) => <option key={y} value={y}>{y}</option>)}
    </select>
  );
}

const cellCls = 'py-1.5 px-2 text-right font-mono text-xs whitespace-nowrap';

export function MonthlyRow({ code, name, months, total, bold, tone, testId, indent = true }) {
  const cls = `${cellCls} ${bold ? 'font-semibold' : ''} ${tone || ''}`;
  return (
    <tr className={`border-b border-[var(--glass-border)] ${bold ? 'bg-[var(--card-surface)]' : 'hover:bg-foreground/5'}`} data-testid={testId}>
      <td className="py-1.5 px-2 font-mono text-xs text-muted-foreground sticky left-0 bg-[var(--card-surface)]">{code}</td>
      <td className={`py-1.5 px-2 text-xs whitespace-nowrap sticky left-[88px] bg-[var(--card-surface)] ${bold ? 'font-semibold uppercase' : indent ? 'pl-5' : ''}`}>{name}</td>
      {months.map((v, i) => <td key={i} className={cls}>{fmtCell(v)}</td>)}
      {total !== undefined && <td className={`${cls} border-l border-[var(--glass-border)]`}>{fmtCell(total)}</td>}
    </tr>
  );
}

export function MonthlyHead({ labels, year, withTotal }) {
  return (
    <thead className="sticky top-0 z-10 bg-[var(--card-surface)] backdrop-blur-sm">
      <tr className="text-left text-[10px] uppercase text-muted-foreground border-b border-[var(--glass-border)]">
        <th className="py-2 px-2 sticky left-0 bg-[var(--card-surface)]">Kode</th>
        <th className="py-2 px-2 sticky left-[88px] bg-[var(--card-surface)]">Akun</th>
        {labels.map((l) => <th key={l} className="py-2 px-2 text-right whitespace-nowrap">{l} {String(year).slice(2)}</th>)}
        {withTotal && <th className="py-2 px-2 text-right border-l border-[var(--glass-border)]">Total</th>}
      </tr>
    </thead>
  );
}
