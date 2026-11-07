export type InvoiceStatus =
  | "uploaded"
  | "queued"
  | "extracting"
  | "needs_review"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "exported"
  | "failed";

export type InvoiceListItem = {
  id: string;
  invoice_number: string;
  vendor: {
    id: string;
    name: string;
  } | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string | null;
  subtotal: string | null;
  total_amount: string | null;
  amount_due: string | null;
  status: InvoiceStatus;
  document: {
    id: string;
    filename: string;
    status: string;
  } | null;
  created_at: string;
};

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type InvoiceListParams = {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: InvoiceStatus | "";
};