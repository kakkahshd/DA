import React, { lazy } from 'react';
import HubTabs from './HubTabs';

// IA v2.1 — konsolidasi 6 laporan keuangan inti -> 1 hub bertab.
const RahazaTrialBalanceModule  = lazy(() => import('../RahazaTrialBalanceModule'));
const RahazaGeneralLedgerModule = lazy(() => import('../RahazaGeneralLedgerModule'));
const RahazaPnLModule           = lazy(() => import('../RahazaPnLModule'));
const RahazaBalanceSheetModule  = lazy(() => import('../RahazaBalanceSheetModule'));
const RahazaCashFlowModule      = lazy(() => import('../RahazaCashFlowModule'));
const RahazaAPAgingModule       = lazy(() => import('../RahazaAPAgingModule'));
const RahazaFGValuationModule   = lazy(() => import('../RahazaFGValuationModule'));
const RahazaWorksheetModule     = lazy(() => import('../finance/RahazaWorksheetModule'));
const RahazaPnLMonthlyModule    = lazy(() => import('../finance/RahazaPnLMonthlyModule'));
const RahazaBalanceSheetMonthlyModule = lazy(() => import('../finance/RahazaBalanceSheetMonthlyModule'));

export default function FinanceReportsHub(props) {
  return (
    <HubTabs
      hubId="fin-reports-hub"
      title="Laporan Keuangan"
      subtitle="Satu pintu laporan inti: Neraca Saldo, Neraca Lajur, Buku Besar, Laba Rugi (periode & 12 bulan), Neraca (per tanggal & 12 bulan), Arus Kas, Aging Hutang, Nilai Persediaan FG."
      tabs={[
        { key: 'tb', label: 'Neraca Saldo', Component: RahazaTrialBalanceModule },
        { key: 'worksheet', label: 'Neraca Lajur', Component: RahazaWorksheetModule },
        { key: 'gl', label: 'Buku Besar', Component: RahazaGeneralLedgerModule },
        { key: 'pnl', label: 'Laba Rugi', Component: RahazaPnLModule },
        { key: 'pnl12', label: 'Laba Rugi 12 Bln', Component: RahazaPnLMonthlyModule },
        { key: 'bs', label: 'Neraca', Component: RahazaBalanceSheetModule },
        { key: 'bs12', label: 'Neraca 12 Bln', Component: RahazaBalanceSheetMonthlyModule },
        { key: 'cashflow', label: 'Arus Kas', Component: RahazaCashFlowModule },
        { key: 'apaging', label: 'Aging Hutang', Component: RahazaAPAgingModule },
        { key: 'fgval', label: 'Nilai Persediaan FG', Component: RahazaFGValuationModule },
      ]}
      {...props}
    />
  );
}
