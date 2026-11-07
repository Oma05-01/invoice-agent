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