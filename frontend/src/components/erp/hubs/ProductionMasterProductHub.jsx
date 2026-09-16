import React, { lazy, Suspense } from 'react';

// 2026-09-12 (keputusan owner): tab "Lokasi Kerja" & "Operator & Skill" dihapus dari
// Master Produk Produksi — tidak relevan di sini. Master Lokasi pindah ke
// Gudang → Master Item → tab "Lokasi Gudang"; Operator/karyawan tetap di Portal HR.
const RahazaModelsAndBOMModule = lazy(() => import('../RahazaModelsAndBOMModule'));

const Spinner = () => (
  <div className="flex items-center justify-center h-40">
    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[hsl(var(--primary))]" />
  </div>
);

export default function ProductionMasterProductHub(props) {
  return (
    <div data-testid="prod-master-product-hub">
      <Suspense fallback={<Spinner />}>
        <RahazaModelsAndBOMModule {...props} />
      </Suspense>
    </div>
  );
}
