export type SpendDimension = "vendor" | "account" | "month";

export interface SpendReportFilters {
  dimension: SpendDimension;
  startDate: string;
  endDate: string;
  limit?: number;
  currency?: string;
}

export interface VendorSpendRow {
  vendor_id: string | null;
  vendor_name: string;
  amount: string;
}

export interface AccountSpendRow {
  account_id: string;
  account_code: string;
  account_name: string;
  amount: string;
}

export interface MonthlySpendRow {
  month: string;
  amount: string;
}

export type SpendReportRow =
  | VendorSpendRow
  | AccountSpendRow
  | MonthlySpendRow;

export interface SpendCurrencyReport {
  currency: string;
  rows: SpendReportRow[];
  total_expenditure: string;
  returned_expenditure: string;
  group_count: number;
  returned_group_count: number;
  is_truncated: boolean;
}

export interface SpendReportResponse {
  dimension: SpendDimension;
  period: {
    start_date: string;
    end_date: string;
  };
  limit_per_currency: number;
  currencies: SpendCurrencyReport[];
  report_basis: string;
}
