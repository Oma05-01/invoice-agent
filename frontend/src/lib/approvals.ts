export interface ApprovalRequestSummary {
  id: string;
  status: string;
  submitted_by: {
    id: string;
    username: string;
  };
  submission_note: string;
  submitted_at: string;
  invoice: {
    id: string;
    invoice_number: string | null;
    invoice_date: string | null;
    currency: string | null;
    total_amount: string | null;
    vendor: {
      id: string;
      legal_name: string;
    } | null;
  };
}

export interface ApprovalQueueResponse {
  count: number;
  results: ApprovalRequestSummary[];
}

export interface ApprovalDecision {
  id: string;
  outcome: string;
  comment: string;
  decided_by: {
    id: string;
    username: string;
  };
  decided_at: string;
}

export interface ApprovalDetailResponse {
  approval_request: ApprovalRequestSummary;
  invoice: {
    status: string;
    description: string;
    financial_data: {
      subtotal: string | null;
      tax_amount: string | null;
      other_charges: string | null;
      total_amount: string | null;
      amount_due: string | null;
    };
    document: {
      id: string;
      filename: string;
      status: string;
      content_type: string;
    } | null;
  };
  decision: ApprovalDecision | null;
}

export interface ApprovalActionResponse {
  message: string;
  approval_request_id?: string;
  decision_id?: string;
  decision?: string;
  invoice_id: string;
  invoice_status: string;
  previous_approval_request_id?: string;
  previous_approval_status?: string;
  rejection_comment?: string;
}

async function getErrorMessage(response: Response): Promise<string> {
  const data: unknown = await response.json().catch(() => null);

  if (typeof data === "object" && data !== null) {
    if ("detail" in data && typeof data.detail === "string") {
      return data.detail;
    }

    if ("message" in data && typeof data.message === "string") {
      return data.message;
    }

    return JSON.stringify(data);
  }

  return `The approval request failed with status ${response.status}.`;
}

async function getCSRFToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Unable to obtain a security token.");
  }

  const data = (await response.json()) as {
    csrfToken: string;
  };

  return data.csrfToken;
}

export async function fetchApprovalQueue(
  organizationId: string,
): Promise<ApprovalQueueResponse> {
  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/approvals/`,
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
    throw new Error(await getErrorMessage(response));
  }

  return (await response.json()) as ApprovalQueueResponse;
}

export async function fetchApprovalDetail(
  organizationId: string,
  approvalRequestId: string,
): Promise<ApprovalDetailResponse> {
  const response = await fetch(
    `/api/organizations/${encodeURIComponent(organizationId)}/approvals/${encodeURIComponent(approvalRequestId)}/`,
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
    throw new Error(await getErrorMessage(response));
  }

  return (await response.json()) as ApprovalDetailResponse;
}

async function postApprovalAction(
  url: string,
  payload: object,
): Promise<ApprovalActionResponse> {
  const csrfToken = await getCSRFToken();

  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return (await response.json()) as ApprovalActionResponse;
}

function approvalActionUrl(
  organizationId: string,
  approvalRequestId: string,
  action: "approve" | "reject" | "return-to-review",
): string {
  return (
    `/api/organizations/${encodeURIComponent(organizationId)}` +
    `/approvals/${encodeURIComponent(approvalRequestId)}/${action}/`
  );
}

export function approveInvoice(
  organizationId: string,
  approvalRequestId: string,
  comment: string,
): Promise<ApprovalActionResponse> {
  return postApprovalAction(
    approvalActionUrl(organizationId, approvalRequestId, "approve"),
    { comment: comment.trim() },
  );
}

export function rejectInvoice(
  organizationId: string,
  approvalRequestId: string,
  comment: string,
): Promise<ApprovalActionResponse> {
  return postApprovalAction(
    approvalActionUrl(organizationId, approvalRequestId, "reject"),
    { comment: comment.trim() },
  );
}

export function returnInvoiceToReview(
  organizationId: string,
  approvalRequestId: string,
  returnReason: string,
): Promise<ApprovalActionResponse> {
  return postApprovalAction(
    approvalActionUrl(
      organizationId,
      approvalRequestId,
      "return-to-review",
    ),
    { return_reason: returnReason.trim() },
  );
}