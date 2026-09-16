import { useState } from 'react';
import { KeyRound, Loader2 } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import apiFetch from '@/lib/apiFetch';

// Ditampilkan setelah login bila server menandai `must_change_password`
// (akun hasil impor master memakai kata sandi awal bersama).
export default function ForcePasswordChange({ token, email, oldPassword, onDone }) {
  const [pw1, setPw1] = useState('');
  const [pw2, setPw2] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (pw1 !== pw2) return setError('Konfirmasi kata sandi tidak sama');
    setLoading(true);
    try {
      await apiFetch('/auth/change-password', {
        method: 'POST', token,
        body: { old_password: oldPassword, new_password: pw1 },
      });
      onDone();
    } catch (err) {
      setError(err.detail || err.message || 'Gagal mengganti kata sandi');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-ambient noise-overlay flex items-center justify-center p-6" data-testid="force-password-page">
      <GlassCard className="w-full max-w-md p-8 space-y-5">
        <div className="flex items-center gap-3">
          <KeyRound className="w-6 h-6 text-[hsl(var(--primary))]" />
          <h2 className="text-lg font-semibold">Ganti kata sandi awal</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Akun <b>{email}</b> masih memakai kata sandi awal. Buat kata sandi baru (minimal 8 karakter,
          huruf + angka) sebelum masuk.
        </p>
        {error && <p className="text-red-500 text-sm" data-testid="force-password-error">{error}</p>}
        <form onSubmit={submit} className="space-y-4">
          <GlassInput type="password" placeholder="Kata sandi baru" value={pw1}
            onChange={(e) => setPw1(e.target.value)} required data-testid="force-password-new" />
          <GlassInput type="password" placeholder="Ulangi kata sandi baru" value={pw2}
            onChange={(e) => setPw2(e.target.value)} required data-testid="force-password-confirm" />
          <Button type="submit" disabled={loading} className="w-full" data-testid="force-password-submit">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Simpan & masuk'}
          </Button>
        </form>
      </GlassCard>
    </div>
  );
}
