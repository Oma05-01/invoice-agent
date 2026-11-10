import type {
  InvoiceListItem,
  InvoiceListParams,
  PaginatedResponse,
} from "@/types/invoice";

export async function fetchInvoices(
  organizationId: string,
  params: InvoiceListParams = {},
): Promise<PaginatedResponse<InvoiceListItem>> {
  const query = new URLSearchParams();

  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));

  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }

  if (params.status) {
    query.set("status", params.status);
  }

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/?${query.toString()}`,
    {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    },
  );

  if (!response.ok) {
    let message = `Unable to retrieve invoices (${response.status}).`;

    try {
      const data = await response.json();

      if (typeof data.detail === "string") {
        message = data.detail;
      }
    } catch {
      // Retain the default error message.
    }

    throw new Error(message);
  }

  return response.json() as Promise<
    PaginatedResponse<InvoiceListItem>
  >;
}

type QueueInvoiceResponse = {
  message: string;
  invoice_id: string;
  task_id: string;
  outbox_event_id: string;
  status: string;
};

export async function queueInvoiceProcessing(
  organizationId: string,
  invoiceId: string,
): Promise<QueueInvoiceResponse> {
  // Obtain a fresh CSRF token.
  const csrfResponse = await fetch("/api/auth/csrf/", {
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to establish a secure connection.");
  }

  const csrfData: { csrfToken: string } =
    await csrfResponse.json();

  // Request a new processing attempt.
  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/process/`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfData.csrfToken,
      },
      body: JSON.stringify({}),
    },
  );

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));

    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Unable to queue invoice (${response.status}).`,
    );
  }

  return response.json() as Promise<QueueInvoiceResponse>;
}

export interface InvoiceReviewDocument {
  id: string;
  original_filename: string;
  content_type: string;
}

export interface InvoiceReviewResponse {
  invoice: {
    id: string;
    number: string | null;
    status: string;
  };
  document: InvoiceReviewDocument | null;
  [key: string]: unknown;
}

export async function fetchInvoiceReview(
  organizationId: string,
  invoiceId: string,
): Promise<InvoiceReviewResponse> {
  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/review/`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    let message = "Unable to load invoice review.";

    try {
      const errorData = await response.json();
      message = errorData.detail ?? message;
    } catch {
      // Keep the fallback message if the response is not JSON.
    }

    throw new Error(message);
  }

  return response.json() as Promise<InvoiceReviewResponse>;
}

export function getInvoiceDocumentPreviewUrl(
  organizationId: string,
  documentId: string,
): string {
  return (
    `/api/organizations/${encodeURIComponent(organizationId)}` +
    `/documents/${encodeURIComponent(documentId)}/preview/`
  );
}

export interface Vendor {
  id: string;
  legal_name: string;
  display_name: string | null;
  vendor_code: string | null;
  tax_identification_number: string | null;
  address: string | null;
}

interface VendorListResponse {
  count: number;
  has_more: boolean;
  results: Vendor[];
}

export async function fetchVendors(
  organizationId: string,
  search = "",
): Promise<VendorListResponse> {
  const params = new URLSearchParams();

  if (search.trim()) {
    params.set("search", search.trim());
  }

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/vendors/?${params.toString()}`,
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error("Unable to retrieve registered vendors.");
  }

  return response.json() as Promise<VendorListResponse>;
}

export interface VendorCreatePayload {
  legal_name: string;
  display_name?: string;
  vendor_code?: string;
  tax_identification_number?: string;
  email?: string;
  phone?: string;
  address?: string;
}

export interface VendorCreateResponse {
  message: string;
  vendor: Vendor;
}

export async function createVendor(
  organizationId: string,
  vendor: VendorCreatePayload,
): Promise<VendorCreateResponse> {
  // Obtain a fresh CSRF token.
  const csrfResponse = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const csrfData = (await csrfResponse.json()) as {
    csrfToken: string;
  };

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/vendors/`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrfData.csrfToken,
      },
      body: JSON.stringify(vendor),
    },
  );

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message =
      typeof data.detail === "string"
        ? data.detail
        : Object.entries(data)
            .map(([field, errors]) => {
              const errorText = Array.isArray(errors)
                ? errors.join(" ")
                : String(errors);

              return `${field}: ${errorText}`;
            })
            .join(" ");

    throw new Error(
      message || "Unable to create vendor.",
    );
  }

  return data as VendorCreateResponse;
}

export async function assignInvoiceVendor(
  organizationId: string,
  invoiceId: string,
  vendorId: string,
  correctionReason: string,
) {
  // Obtain a fresh CSRF token.
  const csrfResponse = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const csrfData = (await csrfResponse.json()) as {
    csrfToken: string;
  };

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/vendor/`,
    {
      method: "PATCH",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrfData.csrfToken,
      },
      body: JSON.stringify({
        vendor_id: vendorId,
        correction_reason: correctionReason,
      }),
    },
  );

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.detail ?? "Unable to assign the invoice vendor.",
    );
  }

  return data;
}

export interface InvoiceHeaderCorrections {
  invoice_number: string;
  invoice_date: string | null;
  due_date: string | null;
  currency: string | null;
  subtotal: string | null;
  other_charges: string | null;
  total_amount: string | null;
  amount_due: string | null;
  description: string;
  correction_reason: string;
}

export async function updateInvoiceHeader(
  organizationId: string,
  invoiceId: string,
  corrections: InvoiceHeaderCorrections,
) {
  const csrfResponse = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const csrfData = (await csrfResponse.json()) as {
    csrfToken: string;
  };

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/review/`,
    {
      method: "PATCH",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrfData.csrfToken,
      },
      body: JSON.stringify(corrections),
    },
  );

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message =
      data.detail ??
      (typeof data === "object"
        ? JSON.stringify(data)
        : "Unable to save invoice corrections.");

    throw new Error(message);
  }

  return data;
}

export interface InvoiceLineItemCorrections {
  description?: string;
  quantity?: string | null;
  unit_price?: string | null;
  tax_rate?: string | null;
  line_total?: string | null;
  ledger_code?: string;
  correction_reason: string;
}

export interface InvoiceLineItemMutationResponse {
  message: string;
  line_item?: Record<string, unknown>;
  line_item_id?: string;
  validation?: {
    new_findings: number;
    automatically_resolved_issue_ids: string[];
  };
}

async function performInvoiceMutation<T>(
  url: string,
  method: "POST" | "PATCH" | "DELETE",
  payload: object,
): Promise<T> {
  const csrfResponse = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const csrfData = (await csrfResponse.json()) as {
    csrfToken: string;
  };

  const response = await fetch(url, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrfData.csrfToken,
    },
    body: JSON.stringify(payload),
  });

  const data: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    let message = "The invoice line-item operation failed.";

    if (
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string"
    ) {
      message = data.detail;
    } else if (data !== null) {
      message = JSON.stringify(data);
    }

    throw new Error(message);
  }

  return data as T;
}

export async function addInvoiceLineItem(
  organizationId: string,
  invoiceId: string,
  corrections: InvoiceLineItemCorrections & {
    description: string;
  },
): Promise<InvoiceLineItemMutationResponse> {
  return performInvoiceMutation(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/line-items/`,
    "POST",
    corrections,
  );
}

export async function updateInvoiceLineItem(
  organizationId: string,
  invoiceId: string,
  lineItemId: string,
  corrections: InvoiceLineItemCorrections,
): Promise<InvoiceLineItemMutationResponse> {
  return performInvoiceMutation(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/line-items/${encodeURIComponent(lineItemId)}/`,
    "PATCH",
    corrections,
  );
}

export async function deleteInvoiceLineItem(
  organizationId: string,
  invoiceId: string,
  lineItemId: string,
  correctionReason: string,
): Promise<InvoiceLineItemMutationResponse> {
  return performInvoiceMutation(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/line-items/${encodeURIComponent(lineItemId)}/`,
    "DELETE",
    {
      correction_reason: correctionReason,
    },
  );
}

export interface InvoiceSubmissionBlocker {
  code: string;
  field_name: string;
  message: string;
}

export interface InvoiceSubmissionResponse {
  message: string;
  invoice_id: string;
  approval_request_id: string;
  status: string;
  automatically_resolved_issue_ids: string[];
}

export class InvoiceSubmissionError extends Error {
  blockers: InvoiceSubmissionBlocker[];

  constructor(
    message: string,
    blockers: InvoiceSubmissionBlocker[] = [],
  ) {
    super(message);
    this.name = "InvoiceSubmissionError";
    this.blockers = blockers;
  }
}

export async function submitInvoiceForApproval(
  organizationId: string,
  invoiceId: string,
  submissionNote: string,
): Promise<InvoiceSubmissionResponse> {
  const csrfResponse = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!csrfResponse.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const csrfData = (await csrfResponse.json()) as {
    csrfToken: string;
  };

  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(invoiceId)}/submit-review/`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrfData.csrfToken,
      },
      body: JSON.stringify({
        submission_note: submissionNote.trim(),
      }),
    },
  );

  const data: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const record =
      typeof data === "object" && data !== null
        ? (data as Record<string, unknown>)
        : {};

    const blockers = Array.isArray(record.blockers)
      ? record.blockers.filter(
          (item): item is InvoiceSubmissionBlocker =>
            typeof item === "object" &&
            item !== null &&
            "code" in item &&
            "field_name" in item &&
            "message" in item &&
            typeof item.code === "string" &&
            typeof item.field_name === "string" &&
            typeof item.message === "string",
        )
      : [];

    const message =
      typeof record.message === "string"
        ? record.message
        : typeof record.detail === "string"
          ? record.detail
          : "Unable to submit this invoice for approval.";

    throw new InvoiceSubmissionError(message, blockers);
  }

  return data as InvoiceSubmissionResponse;
}

