import React, { lazy } from 'react';
import HubTabs from './HubTabs';

// IA v2.1 — konsolidasi master akuntansi -> 1 hub bertab.
const RahazaCOAModule             = lazy(() => import('../RahazaCOAModule'));
const RahazaPostingProfilesModule = lazy(() => import('../RahazaPostingProfilesModule'));
const EmployeeExpenseGLMappingModule = lazy(() => import('../EmployeeExpenseGLMappingModule'));
const EmployeeExpenseCategoryMasterModule = lazy(() => import('../EmployeeExpenseCategoryMasterModule'));
const RahazaPeriodsModule         = lazy(() => import('../RahazaPeriodsModule'));
const AdminSetupPanelModule       = lazy(() => import('../AdminSetupPanelModule'));
const RahazaCoaAutoModule         = lazy(() => import('../RahazaCoaAutoModule'));
const RahazaOpeningBalanceModule  = lazy(() => import('../finance/RahazaOpeningBalanceModule'));
const RahazaMasterFillModule      = lazy(() => import('../finance/RahazaMasterFillModule'));

export default function FinanceAccountingMasterHub(props) {
  return (
    <HubTabs
      hubId="fin-accounting-master-hub"
      title="Master Akuntansi"
      subtitle="Konfigurasi akuntansi: Bagan Akun, Saldo Awal Go-Live, Profil Posting, Pemetaan GL, Kategori Expense, Periode, Setup."
      tabs={[
        { key: 'coa', label: 'Bagan Akun', Component: RahazaCOAModule },
        { key: 'opening', label: 'Saldo Awal', Component: RahazaOpeningBalanceModule },
        { key: 'fill', label: 'Impor Harga · Rekening · BOM', Component: RahazaMasterFillModule },
        { key: 'posting', label: 'Profil Posting', Component: RahazaPostingProfilesModule },
        { key: 'coa-auto', label: 'Auto Akun (Subledger)', Component: RahazaCoaAutoModule },
        { key: 'glmap', label: 'Pemetaan GL', Component: EmployeeExpenseGLMappingModule },
        { key: 'expcat', label: 'Kategori Expense', Component: EmployeeExpenseCategoryMasterModule },
        { key: 'periods', label: 'Periode', Component: RahazaPeriodsModule },
        { key: 'setup', label: 'Setup Akuntansi', Component: AdminSetupPanelModule },
      ]}
      {...props}
    />
  );
}
