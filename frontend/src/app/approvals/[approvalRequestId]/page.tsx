"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  FileText,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { ProtectedRoute } from "@/components/protected-route";
import { useAuth } from "@/components/auth-provider";

import {
  approveInvoice,
  rejectInvoice,
  returnInvoiceToReview,
  fetchApprovalDetail,
  type ApprovalDetailResponse,
} from "@/lib/approvals";

import { getInvoiceDocumentPreviewUrl } from "@/lib/invoices";

const APPROVER_ROLES = [
  "owner",
  "finance_admin",
  "finance_reviewer",
];

const RETURN_ROLES = [
  "owner",
  "finance_admin",
  "finance_operator",
];

const DETAIL_ROLES = [
  ...APPROVER_ROLES,
  ...RETURN_ROLES,
];

type DecisionAction =
  | "approve"
  | "reject"
  | "return"
  | null;

function formatKey(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatMoney(
  amount: string | null,
  currency: string | null,
): string {
  if (amount === null) return "Not provided";

  const value = Number(amount);

  if (!Number.isFinite(value)) return amount;

  if (!currency) {
    return value.toLocaleString("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency,
    }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString("en-NG")}`;
  }
}

function formatDate(value: string | null): string {
  if (!value) return "Not provided";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-NG", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function StatusLabel({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-blue-50 text-blue-700",
    approved: "bg-green-50 text-green-700",
    rejected: "bg-red-50 text-red-700",
    needs_review: "bg-amber-50 text-amber-700",
  };

  return (
    <span
      className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
        styles[status] ?? "bg-gray-100 text-gray-700"
      }`}
    >
      {formatKey(status)}
    </span>
  );
}

function ApprovalDetailWorkspace() {
  const { user } = useAuth();

  const params = useParams<{
    approvalRequestId: string;
  }>();

  const searchParams = useSearchParams();

  const approvalRequestId = params.approvalRequestId;
  const organizationId =
    searchParams.get("organizationId") ?? "";

  const membership = user?.organizations.find(
    (organization) => organization.id === organizationId,
  );

  const role = membership?.role ?? "";

  const [detail, setDetail] =
    useState<ApprovalDetailResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [comment, setComment] = useState("");
  const [returnReason, setReturnReason] = useState("");

  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");

  const [busyAction, setBusyAction] =
    useState<DecisionAction>(null);

  useEffect(() => {
    let active = true;

    async function loadDetail() {
      if (!organizationId || !approvalRequestId) {
        setError("The organization or approval request ID is missing.");
        setLoading(false);
        return;
      }

      if (!membership || !DETAIL_ROLES.includes(role)) {
        setError(
          "Your organization membership does not permit access to this approval request.",
        );
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError("");

        const result = await fetchApprovalDetail(
          organizationId,
          approvalRequestId,
        );

        if (active) {
          setDetail(result);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load the approval request.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadDetail();

    return () => {
      active = false;
    };
  }, [organizationId, approvalRequestId, role, membership]);

  async function refreshDetail() {
    const result = await fetchApprovalDetail(
      organizationId,
      approvalRequestId,
    );

    setDetail(result);
  }

  async function handleApprove() {
    if (!detail || busyAction) return;

    setBusyAction("approve");
    setActionError("");
    setActionMessage("");

    try {
      const result = await approveInvoice(
        organizationId,
        approvalRequestId,
        comment,
      );

      setActionMessage(result.message);
      setComment("");

      try {
        await refreshDetail();
      } catch {
        setActionError(
          "The approval decision was recorded, but the page could not refresh. Reload to see the updated status.",
        );
      }
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "Unable to approve this invoice.",
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleReject() {
    if (!detail || busyAction) return;

    if (!comment.trim()) {
      setActionError(
        "A rejection explanation is required.",
      );
      return;
    }

    setBusyAction("reject");
    setActionError("");
    setActionMessage("");

    try {
      const result = await rejectInvoice(
        organizationId,
        approvalRequestId,
        comment,
      );

      setActionMessage(result.message);
      setComment("");

      try {
        await refreshDetail();
      } catch {
        setActionError(
          "The rejection was recorded, but the page could not refresh. Reload to see the updated status.",
        );
      }
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "Unable to reject this invoice.",
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleReturnToReview() {
    if (!detail || busyAction) return;

    if (!returnReason.trim()) {
      setActionError(
        "A reason for returning the invoice is required.",
      );
      return;
    }

    setBusyAction("return");
    setActionError("");
    setActionMessage("");

    try {
      const result = await returnInvoiceToReview(
        organizationId,
        approvalRequestId,
        returnReason,
      );

      setActionMessage(result.message);
      setReturnReason("");

      try {
        await refreshDetail();
      } catch {
        setActionError(
          "The invoice was returned for review, but the page could not refresh. Reload to see the updated status.",
        );
      }
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "Unable to return this invoice.",
      );
    } finally {
      setBusyAction(null);
    }
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-[#f5f7fb] p-8">
        <p className="text-sm text-gray-500">
          Loading approval details...
        </p>
      </main>
    );
  }

  if (error || !detail) {
    return (
      <main className="min-h-screen space-y-5 bg-[#f5f7fb] p-8">
        <Link
          href={`/approvals?organizationId=${encodeURIComponent(organizationId)}`}
          className="inline-flex items-center gap-2 text-sm text-blue-700 hover:underline"
        >
          <ArrowLeft size={15} />
          Back to approval queue
        </Link>

        <div className="rounded-xl border border-red-200 bg-red-50 p-5">
          <h1 className="font-semibold text-red-800">
            Unable to load approval request
          </h1>

          <p className="mt-2 text-sm text-red-700">
            {error || "The approval request could not be loaded."}
          </p>
        </div>
      </main>
    );
  }

  const request = detail.approval_request;
  const invoice = detail.invoice;
  const financialData = invoice.financial_data;
  const document = invoice.document;

  const isPending = request.status === "pending";

  const isSubmitter =
    request.submitted_by.id === user?.id;

  const canDecide =
    APPROVER_ROLES.includes(role) &&
    isPending &&
    !isSubmitter;

  const canReturn =
    RETURN_ROLES.includes(role) &&
    request.status === "rejected" &&
    invoice.status === "rejected";

  const documentPreviewUrl = document
    ? getInvoiceDocumentPreviewUrl(
        organizationId,
        document.id,
      )
    : null;

  return (
    <main className="min-h-screen bg-[#f5f7fb]">
      <header className="border-b border-slate-200 bg-white px-5 py-5 sm:px-8">
        <div className="mx-auto max-w-[1500px]">
          <Link
            href={`/approvals?organizationId=${encodeURIComponent(organizationId)}`}
            className="mb-3 inline-flex items-center gap-2 text-xs font-medium text-slate-500 hover:text-blue-700"
          >
            <ArrowLeft size={14} />
            Back to approval queue
          </Link>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs text-slate-400">
                Approval workspace
              </p>

              <h1 className="mt-1 text-2xl font-bold text-slate-900">
                {request.invoice.invoice_number ??
                  "Unnumbered invoice"}
              </h1>

              <p className="mt-1 text-sm text-slate-500">
                {request.invoice.vendor?.legal_name ??
                  "Unassigned supplier"}
              </p>
            </div>

            <StatusLabel status={request.status} />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] space-y-6 p-5 sm:p-8">
        {actionMessage && (
          <div
            role="status"
            className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700"
          >
            {actionMessage}
          </div>
        )}

        {actionError && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          >
            {actionError}
          </div>
        )}

        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(340px,0.8fr)]">
          {/* Original document */}
          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex items-center gap-3 border-b border-slate-100 p-4">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <FileText size={18} />
              </div>

              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-slate-900">
                  Original invoice document
                </h2>

                <p className="truncate text-xs text-slate-500">
                  {document?.filename ?? "No source document"}
                </p>
              </div>
            </div>

            {documentPreviewUrl ? (
              <iframe
                title="Original invoice PDF"
                src={documentPreviewUrl}
                className="h-[75vh] min-h-[600px] w-full bg-slate-100"
              />
            ) : (
              <div className="flex min-h-[400px] items-center justify-center p-8 text-center">
                <div>
                  <FileText
                    size={32}
                    className="mx-auto text-slate-300"
                  />

                  <p className="mt-3 text-sm text-slate-600">
                    No source document is attached to this invoice.
                  </p>
                </div>
              </div>
            )}
          </section>

          {/* Decision information */}
          <div className="space-y-5">
            <section className="rounded-xl border border-slate-200 bg-white p-5">
              <div className="flex items-center gap-2">
                <ShieldCheck
                  size={18}
                  className="text-blue-700"
                />

                <h2 className="text-base font-semibold text-slate-900">
                  Approval request
                </h2>
              </div>

              <dl className="mt-4 space-y-4">
                <div>
                  <dt className="text-xs text-slate-500">
                    Submitted by
                  </dt>

                  <dd className="mt-1 text-sm font-medium text-slate-800">
                    {request.submitted_by.username}
                  </dd>
                </div>

                <div>
                  <dt className="text-xs text-slate-500">
                    Submitted at
                  </dt>

                  <dd className="mt-1 text-sm text-slate-800">
                    {formatDate(request.submitted_at)}
                  </dd>
                </div>

                <div>
                  <dt className="text-xs text-slate-500">
                    Submission note
                  </dt>

                  <dd className="mt-1 whitespace-pre-wrap text-sm text-slate-800">
                    {request.submission_note || "No submission note provided."}
                  </dd>
                </div>

                <div>
                  <dt className="text-xs text-slate-500">
                    Invoice status
                  </dt>

                  <dd className="mt-1">
                    <StatusLabel status={invoice.status} />
                  </dd>
                </div>
              </dl>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-base font-semibold text-slate-900">
                Financial summary
              </h2>

              <dl className="mt-4 space-y-3">
                {[
                  ["Subtotal", financialData.subtotal],
                  ["Tax amount", financialData.tax_amount],
                  ["Other charges", financialData.other_charges],
                  ["Amount due", financialData.amount_due],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="flex justify-between gap-3"
                  >
                    <dt className="text-sm text-slate-500">
                      {label}
                    </dt>

                    <dd className="text-sm font-medium text-slate-800">
                      {formatMoney(
                        value as string | null,
                        request.invoice.currency,
                      )}
                    </dd>
                  </div>
                ))}

                <div className="flex justify-between gap-3 border-t border-slate-100 pt-3">
                  <dt className="text-sm font-semibold text-slate-800">
                    Total amount
                  </dt>

                  <dd className="text-base font-bold text-slate-900">
                    {formatMoney(
                      financialData.total_amount,
                      request.invoice.currency,
                    )}
                  </dd>
                </div>
              </dl>

              {invoice.description && (
                <div className="mt-4 border-t border-slate-100 pt-3">
                  <p className="text-xs text-slate-500">
                    Invoice description
                  </p>

                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                    {invoice.description}
                  </p>
                </div>
              )}
            </section>

            {/* Maker-checker warning */}
            {isPending && isSubmitter && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <h3 className="text-sm font-semibold text-amber-900">
                  Independent approval required
                </h3>

                <p className="mt-1 text-xs leading-5 text-amber-800">
                  You submitted this invoice. The maker-checker policy
                  prevents you from approving or rejecting your own
                  submission. Another authorized approver must make
                  the decision.
                </p>
              </div>
            )}

            {/* Approve / Reject */}
            {canDecide && (
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="text-base font-semibold text-slate-900">
                  Record your decision
                </h2>

                <p className="mt-1 text-xs text-slate-500">
                  Review the source document and financial information
                  before making a decision.
                </p>

                <label className="mt-4 block">
                  <span className="mb-1 block text-xs font-medium text-slate-600">
                    Decision comment
                    <span className="ml-1 font-normal text-slate-400">
                      (optional for approval, required for rejection)
                    </span>
                  </span>

                  <textarea
                    value={comment}
                    onChange={(event) =>
                      setComment(event.target.value)
                    }
                    maxLength={2000}
                    rows={4}
                    disabled={busyAction !== null}
                    placeholder="Enter your observations or reasons for the decision."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  />
                </label>

                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={handleApprove}
                    disabled={busyAction !== null}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <CheckCircle2 size={17} />

                    {busyAction === "approve"
                      ? "Approving..."
                      : "Approve invoice"}
                  </button>

                  <button
                    type="button"
                    onClick={handleReject}
                    disabled={
                      busyAction !== null || !comment.trim()
                    }
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-3 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <XCircle size={17} />

                    {busyAction === "reject"
                      ? "Rejecting..."
                      : "Reject invoice"}
                  </button>
                </div>
              </section>
            )}

            {/* Return rejected invoice to review */}
            {canReturn && (
              <section className="rounded-xl border border-amber-200 bg-white p-5">
                <h2 className="text-base font-semibold text-slate-900">
                  Return for correction
                </h2>

                <p className="mt-1 text-xs text-slate-500">
                  Return this rejected invoice to the review stage.
                  Its previous approval decision will remain in the
                  historical record.
                </p>

                <label className="mt-4 block">
                  <span className="mb-1 block text-xs font-medium text-slate-600">
                    Return reason
                  </span>

                  <textarea
                    value={returnReason}
                    onChange={(event) =>
                      setReturnReason(event.target.value)
                    }
                    rows={3}
                    maxLength={1000}
                    disabled={busyAction !== null}
                    placeholder="Explain what needs to be corrected."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100 disabled:bg-slate-50"
                  />
                </label>

                <button
                  type="button"
                  onClick={handleReturnToReview}
                  disabled={
                    busyAction !== null ||
                    !returnReason.trim()
                  }
                  className="mt-3 w-full rounded-lg bg-amber-600 px-4 py-3 text-sm font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busyAction === "return"
                    ? "Returning..."
                    : "Return invoice to review"}
                </button>
              </section>
            )}

            {/* Existing decision */}
            {detail.decision && (
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="text-base font-semibold text-slate-900">
                  Recorded decision
                </h2>

                <div className="mt-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs text-slate-500">
                      Outcome
                    </span>

                    <StatusLabel
                      status={detail.decision.outcome}
                    />
                  </div>

                  <div>
                    <p className="text-xs text-slate-500">
                      Decided by
                    </p>

                    <p className="mt-1 text-sm font-medium text-slate-800">
                      {detail.decision.decided_by.username}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-slate-500">
                      Decision time
                    </p>

                    <p className="mt-1 text-sm text-slate-800">
                      {formatDate(detail.decision.decided_at)}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-slate-500">
                      Comment
                    </p>

                    <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                      {detail.decision.comment || "No comment recorded."}
                    </p>
                  </div>
                </div>
              </section>
            )}

            {!isPending && !detail.decision && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                This approval request is no longer pending.
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

export default function ApprovalDetailPage() {
  return (
    <ProtectedRoute>
      <ApprovalDetailWorkspace />
    </ProtectedRoute>
  );
}