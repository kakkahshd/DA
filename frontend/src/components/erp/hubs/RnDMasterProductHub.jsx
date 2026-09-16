import React, { lazy, Suspense } from 'react';

// 2026-09-12 (keputusan owner): Kategori · Varian/SKU · BOM · Ukuran · Warna PINDAH dari
// Portal Produksi ke Portal RnD sebagai Master Produk (SSOT). Model DA tetap di Produksi.
const RahazaModelsAndBOMModule = lazy(() => import('../RahazaModelsAndBOMModule'));

const Spinner = () => (
  <div className="flex items-center justify-center h-40">
    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[hsl(var(--primary))]" />
  </div>
);

export default function RnDMasterProductHub(props) {
  return (
    <div data-testid="rnd-master-product-hub">
      <Suspense fallback={<Spinner />}>
        <RahazaModelsAndBOMModule {...props} variant="rnd" />
      </Suspense>
    </div>
  );
}
