/**
 * RahazaModelsAndBOMModule — Master Produk, dua wajah (keputusan owner 2026-09-12):
 *   variant="production" → Portal Produksi: HANYA tab Model DA (HPP, SOP, bundle).
 *   variant="rnd"        → Portal RnD → Master Produk (SSOT): Kategori · Varian/SKU · BOM ·
 *                          Ukuran · Warna — satu-satunya penyunting `rahaza_boms`,
 *                          `rahaza_product_categories`, `rahaza_sizes`, `rahaza_colors`.
 * Satu kepala halaman, tab pil berikon + jumlah data, penjelasan singkat per tab.
 */
import { useState, useEffect } from 'react';
import { Shirt, ListTree, Ruler, Boxes, Palette, Tags, FlaskConical, ArrowUpRight, RefreshCw, FileSpreadsheet } from 'lucide-react';
import { apiGet, apiPost } from '@/lib/api';
import { toast } from 'sonner';
import RahazaModelsModule from './RahazaModelsModule';
import RahazaBOMModuleV2 from './RahazaBOMModuleV2';
import RahazaSizesModule from './RahazaSizesModule';
import RahazaVariantsModule from './RahazaVariantsModule';
import RahazaColorsModule from './RahazaColorsModule';
import RahazaProductCategoriesModule from './RahazaProductCategoriesModule';
import RahazaMasterFillModule from './finance/RahazaMasterFillModule';

const ALL_TABS = [
  { key: 'models', label: 'Model DA', icon: Shirt, count: 'models',
    hint: 'Model produksi internal: HPP, harga jual resmi, berat, bundle, Panduan Produksi (SOP · foto · video) yang dibaca Vendor CMT.' },
  { key: 'categories', label: 'Kategori', icon: Tags, count: 'categories',
    hint: 'Kelompok produk & awalan SKU. Dipakai grouping katalog marketing dan filter laporan.' },
  { key: 'variants', label: 'Varian / SKU', icon: Boxes, count: 'variants',
    hint: 'Kombinasi model × warna × ukuran yang menjadi SKU barang jadi.' },
  { key: 'bom', label: 'BOM', icon: ListTree, count: null,
    hint: 'Resep per model + ukuran + warna: 1 pcs potongan (biaya dari kain roll yang benar-benar dipotong) + aksesoris. Dasar HPP produk.' },
  { key: 'fill', label: 'Isi Massal (Excel)', icon: FileSpreadsheet, count: null,
    hint: 'Satu template Excel: harga & satuan beli material, aksesoris/bahan BOM per model, berat model, rekening bank & rekening pencairan toko — unggah, HPP standar dihitung otomatis.' },
  { key: 'sizes', label: 'Ukuran', icon: Ruler, count: 'sizes',
    hint: 'Master ukuran (S · M · L · ALLSIZE …) beserta urutannya.' },
  { key: 'colors', label: 'Warna', icon: Palette, count: 'colors',
    hint: 'Palet warna master (kode 3 huruf) — dipakai varian, BOM per warna, dan potongan cutting.' },
];

const VARIANTS = {
  production: {
    tabs: ['models'],
    eyebrow: 'Portal Produksi · Master Data',
    title: 'Master Produk',
    subtitle: 'Model DA — HPP, harga jual resmi, berat, bundle, dan Panduan Produksi yang dibaca Vendor CMT.',
    icon: Shirt,
    crossLink: { module: 'rnd-master-product-hub', label: 'Kategori · Varian · BOM · Ukuran · Warna kini disunting di Portal RnD → Master Produk' },
  },
  rnd: {
    tabs: ['categories', 'variants', 'bom', 'fill', 'sizes', 'colors'],
    eyebrow: 'Portal RnD · Master Data (SSOT)',
    title: 'Master Produk',
    subtitle: 'Sumber tunggal resep produk CV. Dewi Aditya — kategori, varian/SKU, BOM potongan, ukuran, dan warna. Dipakai Cutting, HPP, dan katalog.',
    icon: FlaskConical,
    crossLink: { module: 'prod-master-product-hub', label: 'Model DA (HPP · SOP · bundle) tetap di Portal Produksi → Master Produk' },
  },
};

const COUNT_ENDPOINTS = {
  models: '/rahaza/models',
  categories: '/rahaza/product-categories',
  variants: '/rahaza/variants',
  sizes: '/rahaza/sizes',
  colors: '/rahaza/colors',
};

const countOf = (d) => (Array.isArray(d) ? d.length : (d?.total ?? d?.pagination?.total ?? (Array.isArray(d?.items) ? d.items.length : null)));

export default function RahazaModelsAndBOMModule({ token, user, headers, userRole, hasPerm, onNavigate, variant = 'production' }) {
  const V = VARIANTS[variant] || VARIANTS.production;
  const TABS = ALL_TABS.filter((t) => V.tabs.includes(t.key));
  const storageKey = variant === 'rnd' ? 'hub_tab_rnd-master-product-hub' : 'models_bom_tab';
  const getInitialTab = () => {
    const stored = sessionStorage.getItem(storageKey);
    if (stored && TABS.some((t) => t.key === stored)) {
      sessionStorage.removeItem(storageKey);
      return stored;
    }
    return TABS[0].key;
  };
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [counts, setCounts] = useState({});
  const [syncing, setSyncing] = useState(false);
  const runMasterSync = async () => {
    setSyncing(true);
    try {
      const r = await apiPost('/rahaza/master/sync', {});
      const v = r.variants || {}; const rd = r.rnd || {};
      toast.success(`Sinkron master selesai · ${v.total} varian (${v.created_from_bom + v.created_from_fg} baru) · ${rd.styles_created} style RnD baru · ${v.variants_without_bom} varian tanpa BOM`);
      setCounts({});
    } catch (e) { toast.error(e?.message || 'Sinkron master gagal'); }
    finally { setSyncing(false); }
  };

  useEffect(() => {
    let alive = true;
    Promise.all(Object.entries(COUNT_ENDPOINTS).filter(([k]) => V.tabs.includes(k)).map(async ([k, ep]) => {
      try { return [k, countOf(await apiGet(ep))]; } catch (e) { return [k, null]; }
    })).then((pairs) => { if (alive) setCounts(Object.fromEntries(pairs)); });
    return () => { alive = false; };
  }, [token, variant]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = TABS.find((t) => t.key === activeTab) || TABS[0];
  const shared = { token, user, headers, userRole, hasPerm, onNavigate };

  return (
    <div className="space-y-5" data-testid={`models-bom-module-${variant}`}>
      <header className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--glass-border)] bg-[var(--card-surface)] shadow-[var(--shadow-card)]">
        <div aria-hidden="true" className="absolute -top-16 -right-10 w-64 h-64 rounded-full blur-[90px] opacity-30 pointer-events-none"
          style={{ background: 'radial-gradient(circle, hsl(var(--primary)), transparent 70%)' }} />
        <div className="relative px-5 lg:px-7 pt-5 pb-4 flex items-start gap-4">
          <div className="hidden sm:grid place-items-center w-11 h-11 rounded-[14px] bg-[hsl(var(--primary)/0.12)] border border-[hsl(var(--primary)/0.22)] shrink-0">
            <V.icon className="w-5 h-5 text-[hsl(var(--primary))]" strokeWidth={2} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              <p className="text-[10px] uppercase tracking-[0.16em] text-foreground/50 font-semibold mb-1">{V.eyebrow}</p>
              {variant === 'rnd' && (
                <button type="button" onClick={runMasterSync} disabled={syncing}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs font-medium border border-[var(--glass-border)] hover:bg-[hsl(var(--primary)/0.08)] disabled:opacity-60"
                  title="Samakan varian SSOT dengan BOM & barang jadi, buat style RnD untuk tiap model, tautkan karyawan↔user"
                  data-testid="master-sync-btn">
                  <RefreshCw className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`} />{syncing ? 'Menyinkron…' : 'Sinkron Master'}
                </button>
              )}
            </div>
            <h1 className="text-xl lg:text-2xl font-bold tracking-tight leading-tight">{V.title}</h1>
            <p className="text-sm text-foreground/55 mt-1 leading-relaxed max-w-3xl">{V.subtitle}</p>
            {V.crossLink && (
              <button type="button" onClick={() => onNavigate && onNavigate(V.crossLink.module)}
                className="mt-2 inline-flex items-center gap-1 text-xs text-[hsl(var(--primary))] hover:underline underline-offset-2"
                data-testid={`master-produk-crosslink-${variant}`}>
                {V.crossLink.label} <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
        <nav className="relative px-3 lg:px-5 pb-3 flex flex-wrap gap-1" role="tablist" aria-label="Bagian Master Produk">
          {TABS.map((t) => {
            const active = t.key === activeTab;
            const n = t.count ? counts[t.count] : null;
            return (
              <button key={t.key} type="button" role="tab" aria-selected={active}
                onClick={() => setActiveTab(t.key)}
                data-testid={`tab-${t.key}`}
                className={[
                  'group inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-sm font-medium border',
                  'transition-[background-color,color,border-color,transform] duration-200 active:scale-[0.98]',
                  active
                    ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-transparent shadow-sm'
                    : 'bg-transparent text-foreground/70 border-transparent hover:bg-[hsl(var(--primary)/0.08)] hover:text-foreground',
                ].join(' ')}>
                <t.icon className="w-4 h-4" strokeWidth={2} />
                <span>{t.label}</span>
                {n !== null && n !== undefined && (
                  <span className={[
                    'inline-flex items-center justify-center min-w-[1.5rem] h-5 px-1.5 rounded-full text-[11px] font-semibold tabular-nums',
                    active ? 'bg-white/20 text-inherit' : 'bg-foreground/[0.07] text-foreground/60',
                  ].join(' ')} data-testid={`tab-${t.key}-count`}>{n}</span>
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <p className="text-[13px] text-foreground/60 px-1 -mt-1" data-testid="models-bom-tab-hint">{current.hint}</p>

      <div key={activeTab} className="animate-in fade-in-0 slide-in-from-bottom-1 duration-200">
        {activeTab === 'models' && <RahazaModelsModule {...shared} embedded />}
        {activeTab === 'categories' && <RahazaProductCategoriesModule token={token} />}
        {activeTab === 'variants' && <RahazaVariantsModule token={token} />}
        {activeTab === 'bom' && <RahazaBOMModuleV2 {...shared} />}
        {activeTab === 'fill' && <RahazaMasterFillModule {...shared} />}
        {activeTab === 'sizes' && <RahazaSizesModule {...shared} />}
        {activeTab === 'colors' && <RahazaColorsModule token={token} />}
      </div>
    </div>
  );
}
