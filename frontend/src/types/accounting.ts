export type AccountType =
  | "asset"
  | "liability"
  | "equity"
  | "income"
  | "expense";

export type JournalStatus =
  | "draft"
  | "posted"
  | "reversed";

export interface AccountingAccount {
  id: string;
  code: string;
  name: string;
  account_type: AccountType;
  description: string;
  parent_id: string | null;
  is_active: boolean;
  is_control_account: boolean;
}

export interface JournalLineAccount {
  id: string;
  code: string;
  name: string;
  account_type: AccountType;
}

export interface JournalLine {
  id: string;
  line_number: number;
  account: JournalLineAccount | null;
  source_line_item_id: string | null;
  description: string;
  debit: string;
  credit: string;
}

export interface JournalEntry {
  id: string;
  source_invoice_id: string | null;
  entry_date: string;
  currency: string;
  reference: string;
  description: string;
  status: JournalStatus;
  created_by_id: string | number | null;
  posted_by_id: string | number | null;
  posted_at: string | null;
  reversal_of_id: string | null;
  reversal_reason: string;
  created_at: string;
  updated_at: string;
  lines: JournalLine[];
}

export interface AccountingAccountListResponse {
  count: number;
  accounts: AccountingAccount[];
}

export interface JournalEntryListResponse {
  count: number;
  journals: JournalEntry[];
}

export interface InitializeChartResponse {
  detail: string;
  count: number;
  accounts: AccountingAccount[];
}

export interface JournalLineCorrections {
  account_id?: string | null;
  debit?: string;
  credit?: string;
  description?: string;
  correction_reason: string;
}

export interface JournalReversalRequest {
  reversal_reason: string;
}

export type BalanceSide = "debit" | "credit" | "zero";

export interface LedgerBalance {
  currency: string;
  amount: string;
  side: BalanceSide;
}

export interface LedgerCurrencyTotals {
  currency: string;
  debit: string;
  credit: string;
}

export interface LedgerTransaction {
  journal_entry_id: string;
  reference: string;
  entry_date: string;
  journal_status: JournalStatus;
  journal_description: string;
  line_id: string;
  line_number: number;
  description: string;
  currency: string;
  debit: string;
  credit: string;
  running_balance: {
    amount: string;
    side: BalanceSide;
  };
}

export interface AccountLedgerResponse {
  account: AccountingAccount;
  period: {
    start_date: string | null;
    end_date: string | null;
  };
  count: number;
  opening_balances: LedgerBalance[];
  transactions: LedgerTransaction[];
  totals_by_currency: LedgerCurrencyTotals[];
  closing_balances: LedgerBalance[];
  report_basis: string;
}

export interface TrialBalanceAccount {
  id: string;
  code: string;
  name: string;
  account_type: AccountType;
  is_active: boolean;
  is_control_account: boolean;
  debit_balance: string;
  credit_balance: string;
}

export interface TrialBalanceCurrencyReport {
  currency: string;
  accounts: TrialBalanceAccount[];
  totals: {
    debit_balance: string;
    credit_balance: string;
  };
  is_balanced: boolean;
}

export interface TrialBalanceResponse {
  as_of_date: string;
  currencies: TrialBalanceCurrencyReport[];
  report_basis: string;
}

export interface IncomeStatementAccountLine {
  account_id: string;
  code: string;
  name: string;
  amount: string;
}

export interface IncomeStatementCurrencyReport {
  currency: string;
  revenue_accounts: IncomeStatementAccountLine[];
  expense_accounts: IncomeStatementAccountLine[];
  total_revenue: string;
  total_expenses: string;
  net_income: string;
}

export interface IncomeStatementResponse {
  period: {
    start_date: string;
    end_date: string;
  };
  currencies: IncomeStatementCurrencyReport[];
  report_basis: string;
}

export interface BalanceSheetAccountLine {
  id: string;
  code: string;
  name: string;
  account_type: AccountType;
  is_active: boolean;
  balance: string;
}

export interface BalanceSheetAccountSection {
  accounts: BalanceSheetAccountLine[];
  total: string;
}

export interface BalanceSheetEquitySection
  extends BalanceSheetAccountSection {
  cumulative_unclosed_earnings: string;
  total_including_unclosed_earnings: string;
}

export interface BalanceSheetCurrencyReport {
  currency: string;
  assets: BalanceSheetAccountSection;
  liabilities: BalanceSheetAccountSection;
  equity: BalanceSheetEquitySection;
  total_liabilities_and_equity: string;
  balance_difference: string;
  is_balanced: boolean;
}

export interface BalanceSheetResponse {
  as_of_date: string;
  currencies: BalanceSheetCurrencyReport[];
  report_basis: string;
}

export interface JournalAdjustmentLineInput {
  account_id: string;
  debit: string;
  credit: string;
  description: string;
}

export interface JournalAdjustmentRequest {
  entry_date: string;
  reason: string;
  description: string;
  lines: JournalAdjustmentLineInput[];
}

export interface JournalAdjustmentResponse {
  journal: JournalEntry;
  adjustment: {
    id: string;
    original_journal_id: string;
    adjustment_journal_id: string;
    reason: string;
  };
  message: string;
}

export interface JournalEntryDateUpdateRequest {
  entry_date: string;
  correction_reason: string;
}

