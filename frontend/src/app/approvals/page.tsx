"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  RefreshCw,
  ShieldCheck,
  FileText,
} from "lucide-react";

import { ProtectedRoute } from "@/components/protected-route";
import { useAuth } from "@/components/auth-provider";
import {
  fetchApprovalQueue,
  type ApprovalRequestSummary,
} from "@/lib/approvals";

const APPROVER_ROLES = [
  "owner",
  "finance_admin",
  "finance_reviewer",
];

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

function formatMoney(
  amount: string | null,
  currency: string | null,
): string {
  if (amount === null) return "Not provided";

  const value = Number(amount);

  if (!Number.isFinite(value)) return amount;

  if (!currency) {
    return new Intl.NumberFormat("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
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

function ApprovalQueueWorkspace() {
  const { user } = useAuth();
  const searchParams = useSearchParams();

  const organizations = user?.organizations ?? [];

  const approverOrganizations = organizations.filter(
    (organization) => APPROVER_ROLES.includes(organization.role),
  );

  const requestedOrganizationId =
    searchParams.get("organizationId") ?? "";

  const [selectedOrganizationId, setSelectedOrganizationId] =
    useState("");

  const organizationId =
    selectedOrganizationId ||
    approverOrganizations.find(
      (organization) =>
        organization.id === requestedOrganizationId,
    )?.id ||
    approverOrganizations[0]?.id ||
    "";

  const [requests, setRequests] = useState<
    ApprovalRequestSummary[]
  >([]);

  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  async function loadQueue(isRefresh = false) {
    if (!organizationId) return;

    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setError("");

    try {
      const result = await fetchApprovalQueue(organizationId);
      setRequests(result.results);
      setCount(result.count);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load the approval queue.",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let active = true;

    async function load() {
      if (!organizationId) {
        setRequests([]);
        setCount(0);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");

      try {
        const result = await fetchApprovalQueue(organizationId);

        if (!active) return;

        setRequests(result.results);
        setCount(result.count);
      } catch (err) {
        if (!active) return;

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load the approval queue.",
        );
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      active = false;
    };
  }, [organizationId]);

  const activeOrganization = approverOrganizations.find(
    (organization) => organization.id === organizationId,
  );

  return (
    <main className="min-h-screen bg-[#f5f7fb]">
      <header className="border-b border-slate-200 bg-white px-5 py-5 sm:px-8">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-4">
          <div>
            <Link
              href="/invoices"
              className="mb-3 inline-flex items-center gap-2 text-xs font-medium text-slate-500 hover:text-blue-700"
            >
              <ArrowLeft size={14} />
              Back to invoices
            </Link>

            <h1 className="text-2xl font-bold text-slate-900">
              Approval queue
            </h1>

            <p className="mt-1 text-sm text-slate-500">
              Review invoices submitted for independent financial approval.
            </p>
          </div>

          {approverOrganizations.length > 0 && (
            <div>
              <label
                htmlFor="approval-organization"
                className="mb-1 block text-xs font-medium text-slate-500"
              >
                Organization
              </label>

              <select
                id="approval-organization"
                value={organizationId}
                onChange={(event) =>
                  setSelectedOrganizationId(event.target.value)
                }
                className="h-10 min-w-[220px] rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500"
              >
                {approverOrganizations.map((organization) => (
                  <option
                    key={organization.id}
                    value={organization.id}
                  >
                    {organization.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-[1400px] space-y-6 p-5 sm:p-8">
        {approverOrganizations.length === 0 ? (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="font-semibold text-amber-900">
              Approval access unavailable
            </h2>

            <p className="mt-2 text-sm text-amber-800">
              Your account does not have an active organization membership
              with approval queue permissions.
            </p>
          </section>
        ) : (
          <>
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs font-medium text-slate-500">
                  Pending requests
                </p>

                <p className="mt-2 text-3xl font-bold text-slate-900">
                  {count}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs font-medium text-slate-500">
                  Active organization
                </p>

                <p className="mt-2 truncate text-lg font-bold text-slate-900">
                  {activeOrganization?.name ?? "—"}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs font-medium text-slate-500">
                  Your role
                </p>

                <p className="mt-2 text-lg font-bold capitalize text-slate-900">
                  {activeOrganization?.role.replace(/_/g, " ") ?? "—"}
                </p>
              </div>
            </section>

            <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                    <ShieldCheck size={20} />
                  </div>

                  <div>
                    <h2 className="text-sm font-bold text-slate-900">
                      Awaiting your decision
                    </h2>

                    <p className="mt-1 text-xs text-slate-500">
                      Requests are ordered by submission time.
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => loadQueue(true)}
                  disabled={refreshing || loading}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  <RefreshCw
                    size={14}
                    className={refreshing ? "animate-spin" : ""}
                  />
                  Refresh
                </button>
              </div>

              {error && (
                <div
                  role="alert"
                  className="m-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
                >
                  {error}
                </div>
              )}

              {loading ? (
                <div className="p-12 text-center text-sm text-slate-500">
                  Loading approval requests...
                </div>
              ) : requests.length === 0 ? (
                <div className="px-5 py-16 text-center">
                  <FileText
                    size={32}
                    className="mx-auto text-slate-300"
                  />

                  <h3 className="mt-4 text-sm font-semibold text-slate-800">
                    No pending approvals
                  </h3>

                  <p className="mt-1 text-xs text-slate-500">
                    New approval requests will appear here after invoices
                    are submitted for approval.
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[850px] text-left">
                    <thead className="bg-slate-50">
                      <tr>
                        {[
                          "Invoice",
                          "Supplier",
                          "Invoice date",
                          "Amount",
                          "Submitted by",
                          "Submitted at",
                          "Action",
                        ].map((heading) => (
                          <th
                            key={heading}
                            className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500"
                          >
                            {heading}
                          </th>
                        ))}
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-slate-100">
                      {requests.map((request) => (
                        <tr
                          key={request.id}
                          className="transition hover:bg-slate-50"
                        >
                          <td className="px-4 py-4">
                            <p className="text-sm font-semibold text-slate-900">
                              {request.invoice.invoice_number ??
                                "Unnumbered invoice"}
                            </p>

                            {request.submission_note && (
                              <p
                                className="mt-1 max-w-[200px] truncate text-xs text-slate-400"
                                title={request.submission_note}
                              >
                                {request.submission_note}
                              </p>
                            )}
                          </td>

                          <td className="px-4 py-4 text-sm text-slate-700">
                            {request.invoice.vendor?.legal_name ??
                              "Unassigned supplier"}
                          </td>

                          <td className="px-4 py-4 text-xs text-slate-500">
                            {formatDate(request.invoice.invoice_date)}
                          </td>

                          <td className="whitespace-nowrap px-4 py-4 text-sm font-semibold text-slate-900">
                            {formatMoney(
                              request.invoice.total_amount,
                              request.invoice.currency,
                            )}
                          </td>

                          <td className="px-4 py-4 text-sm text-slate-600">
                            {request.submitted_by.username}
                          </td>

                          <td className="whitespace-nowrap px-4 py-4 text-xs text-slate-500">
                            {formatDate(request.submitted_at)}
                          </td>

                          <td className="px-4 py-4">
                            <Link
                              href={`/approvals/${request.id}?organizationId=${encodeURIComponent(organizationId)}`}
                              className="inline-flex items-center rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                            >
                              Review request
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  );
}

export default function ApprovalQueuePage() {
  return (
    <ProtectedRoute>
      <ApprovalQueueWorkspace />
    </ProtectedRoute>
  );
}