
export interface FinancialAssistantToolInvocation {
  name: string;
  succeeded: boolean;
}

export interface FinancialReportPeriod {
  start_date: string;
  end_date: string;
}

export interface FinancialReportActivity {
  amount: string;
  gross_debits: string;
  gross_credits: string;
  journal_count: number;
  journal_line_count: number;
}

export interface VendorSpendRow extends FinancialReportActivity {
  vendor_id: string | null;
  vendor_name: string;
}

export interface AccountSpendRow extends FinancialReportActivity {
  account_id: string;
  account_code: string;
  account_name: string;
}

export interface MonthlySpendRow extends FinancialReportActivity {
  month: string;
}

export interface FinancialReportCurrency<T> {
  currency: string;
  rows: T[];
  total_expenditure: string;
  gross_debits: string;
  gross_credits: string;
  journal_count: number;
  journal_line_count: number;
  displayed_rows_expenditure: string;
  group_count: number;
  returned_group_count: number;
  is_truncated: boolean;
}

interface FinancialSpendReportBase {
  period: FinancialReportPeriod;
  limit_per_currency: number;
  report_basis: string;
}

export type FinancialSpendReport =
  | (FinancialSpendReportBase & {
      dimension: "vendor";
      currencies: FinancialReportCurrency<VendorSpendRow>[];
    })
  | (FinancialSpendReportBase & {
      dimension: "account";
      currencies: FinancialReportCurrency<AccountSpendRow>[];
    })
  | (FinancialSpendReportBase & {
      dimension: "month";
      currencies: FinancialReportCurrency<MonthlySpendRow>[];
    });

export interface FinancialAssistantReportArtifact {
  schema_version: 1;
  tool: "spend_by";
  report: FinancialSpendReport;
}

export interface FinancialAssistantChatRequest {
  question: string;
  conversation_id?: string;
}

export interface FinancialAssistantChatResponse {
  conversation_id: string;
  answer: string;
  model: string;
  tool_call_count: number;
  tool_invocations: FinancialAssistantToolInvocation[];
  report_artifacts: FinancialAssistantReportArtifact[];
}

export interface AssistantConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  message_count: number;
}

export interface AssistantConversationListResponse {
  results: AssistantConversationSummary[];
  limit: number;
}

export interface AssistantConversationMessage {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  model: string;
  tool_call_count: number;
  tool_invocations: FinancialAssistantToolInvocation[];
  report_artifacts: FinancialAssistantReportArtifact[];
  created_at: string;
}

export interface AssistantConversationDetailResponse {
  conversation: Omit<AssistantConversationSummary, "message_count">;
  messages: AssistantConversationMessage[];
}

/** UI message shape also supports an unsaved user turn while a request is pending. */
export interface FinancialAssistantDisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  tool_call_count?: number;
  tool_invocations?: FinancialAssistantToolInvocation[];
  report_artifacts?: FinancialAssistantReportArtifact[];
  created_at?: string;
}
