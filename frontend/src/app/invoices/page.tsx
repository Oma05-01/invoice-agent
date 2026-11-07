
"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Filter,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { ProtectedRoute } from "@/components/protected-route";
import { InvoiceUploadDialog } from "@/components/invoice-upload-dialog";

import {
  fetchInvoices,
  queueInvoiceProcessing,
} from "@/lib/invoices";

import type {
  InvoiceListItem,
  InvoiceStatus,
} from "@/types/invoice";

const PAGE_SIZE = 20;

const statusLabels: Record<InvoiceStatus, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  extracting: "Extracting",
  needs_review: "Needs review",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  exported: "Exported",
  failed: "Failed",
};

const statusStyles: Record<InvoiceStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700",
  queued: "bg-blue-50 text-blue-700",
  extracting: "bg-violet-50 text-violet-700",
  needs_review: "bg-amber-50 text-amber-700",
  pending_approval: "bg-indigo-50 text-indigo-700",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-rose-50 text-rose-700",
  exported: "bg-cyan-50 text-cyan-700",
  failed: "bg-red-100 text-red-800",
};

function formatDate(value: string | null) {
  if (!value) return "—";

  const date = new Date(`${value}T00:00:00`);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatAmount(
  value: string | null,
  currency: string | null,
) {
  if (value === null) return "—";

  const amount = Number(value);

  if (!Number.isFinite(amount)) return "—";

  const formatted = new Intl.NumberFormat("en-NG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

  return currency
    ? `${currency} ${formatted}`
    : formatted;
}

function StatusBadge({ status }: { status: InvoiceStatus }) {
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${statusStyles[status]}`}
    >
      {statusLabels[status]}
    </span>
  );
}

function InvoiceWorkspace() {
  const { user } = useAuth();

  const organizations = user?.organizations ?? [];

  const [selectedOrganizationId, setSelectedOrganizationId] =
    useState("");

  const organizationId =
    selectedOrganizationId || organizations[0]?.id || "";

  const [invoices, setInvoices] = useState<InvoiceListItem[]>([]);
  const [count, setCount] = useState(0);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const [uploadOpen, setUploadOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const [queueingInvoiceId, setQueueingInvoiceId] =
  useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<
    InvoiceStatus | ""
  >("");

  const [page, setPage] = useState(1);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function handleRetryProcessing(invoiceId: string) {
  setQueueingInvoiceId(invoiceId);
  setError("");

  try {
    const result = await queueInvoiceProcessing(
      organizationId,
      invoiceId,
    );

    console.log("Invoice processing queued:", result);

    // Reload the invoice table to show its new status.
    setRefreshKey((current) => current + 1);

  } catch (err) {
    setError(
      err instanceof Error
        ? err.message
        : "Unable to retry invoice processing.",
    );
  } finally {
    setQueueingInvoiceId(null);
  }
}

  // Fetch invoices whenever organization, filters or page changes.
  useEffect(() => {
    if (!organizationId) {
        return;
    }

    const controller = new AbortController();

    async function loadInvoices() {
      setLoading(true);
      setError("");

      try {
        const data = await fetchInvoices(organizationId, {
          page,
          pageSize: PAGE_SIZE,
          search,
          status: statusFilter,
        });

        if (controller.signal.aborted) return;

        setInvoices(data.results);
        setCount(data.count);
      } catch (err) {
        if (controller.signal.aborted) return;

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load invoices.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadInvoices();

    return () => controller.abort();
  }, [organizationId, page, search, statusFilter, refreshKey]);

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setPage(1);
    setSearch(searchInput.trim());
  }

  function handleStatusChange(value: string) {
    setStatusFilter(value as InvoiceStatus | "");
    setPage(1);
  }

  function changeOrganization(value: string) {
    setSelectedOrganizationId(value);
    setPage(1);
  }

  function resetFilters() {
    setSearchInput("");
    setSearch("");
    setStatusFilter("");
    setPage(1);
  }

  const totalPages = Math.max(
    1,
    Math.ceil(count / PAGE_SIZE),
  );

  const activeOrganization = organizations.find(
    (organization) => organization.id === organizationId,
  );

  const canQueueProcessing = [
    "owner",
    "finance_admin",
    "finance_operator",
    ].includes(activeOrganization?.role ?? "");

  const canUpload = [
    "owner",
    "finance_admin",
    "finance_operator",
    ].includes(activeOrganization?.role ?? "");

  

return (
  <ProtectedRoute>
    <main className="min-h-screen bg-[#f5f7fb]">
      <header className="border-b border-slate-200 bg-white px-5 py-5 sm:px-8">
        <div className="mx-auto flex max-w-[1500px] flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <p className="text-xs text-slate-400">
              Finance operations / Invoices
            </p>

            <h1 className="mt-2 text-2xl font-bold text-slate-900">
              Invoice management
            </h1>

            <p className="mt-1 text-sm text-slate-500">
              View and track invoices across your organization.
            </p>
          </div>

          <div className="min-w-0">
            <label
              htmlFor="organization"
              className="mb-1.5 block text-xs font-semibold text-slate-500"
            >
              Organization
            </label>

            <select
              id="organization"
              value={organizationId}
              onChange={(event) =>
                changeOrganization(event.target.value)
              }
              className="h-10 min-w-[220px] rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500"
            >
              {organizations.map((organization) => (
                <option
                  key={organization.id}
                  value={organization.id}
                >
                  {organization.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
        {organizations.length === 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="font-semibold text-amber-900">
              No active organization
            </h2>

            <p className="mt-2 text-sm text-amber-800">
              Your account does not currently have an active
              organization membership.
            </p>
          </div>
        ) : (
          <>
            {/* Summary */}
            <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs text-slate-500">
                  Total matching invoices
                </p>

                <p className="mt-2 text-2xl font-bold text-slate-900">
                  {loading ? "—" : count.toLocaleString("en-NG")}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs text-slate-500">
                  Current page
                </p>

                <p className="mt-2 text-2xl font-bold text-slate-900">
                  {page} / {totalPages}
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs text-slate-500">
                  Organization
                </p>

                <p className="mt-2 truncate text-lg font-bold text-slate-900">
                  {activeOrganization?.name ?? "—"}
                </p>
              </div>
            </section>

            {/* Invoice table */}
            <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-col justify-between gap-4 border-b border-slate-100 p-5 lg:flex-row lg:items-center">
                <div>
                  <h2 className="font-bold text-slate-900">
                    All invoices
                  </h2>

                  <p className="mt-1 text-xs text-slate-400">
                    Search and filter your organization&apos;s invoices.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setUploadOpen(true)}
                  disabled={!canUpload}
                  title={
                    canUpload
                      ? "Upload a supplier invoice"
                      : "Your organization role does not permit invoice uploads"
                  }
                  className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Upload invoice
                </button>
              </div>

              {/* Filters */}
              <div className="flex flex-col gap-3 border-b border-slate-100 p-5 lg:flex-row">
                <form
                  onSubmit={handleSearch}
                  className="flex flex-1 gap-2"
                >
                  <div className="relative flex-1">
                    <Search
                      size={17}
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                    />

                    <input
                      type="search"
                      value={searchInput}
                      onChange={(event) =>
                        setSearchInput(event.target.value)
                      }
                      placeholder="Search invoice or supplier..."
                      className="h-10 w-full rounded-lg border border-slate-200 pl-10 pr-3 text-sm outline-none focus:border-blue-500"
                    />
                  </div>

                  <button
                    type="submit"
                    className="rounded-lg bg-slate-900 px-4 text-sm font-medium text-white hover:bg-slate-700"
                  >
                    Search
                  </button>
                </form>

                <div className="flex items-center gap-2">
                  <Filter size={16} className="text-slate-400" />

                  <select
                    value={statusFilter}
                    onChange={(event) =>
                      handleStatusChange(event.target.value)
                    }
                    className="h-10 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500"
                  >
                    <option value="">All statuses</option>

                    {Object.entries(statusLabels).map(
                      ([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ),
                    )}
                  </select>

                  <button
                    type="button"
                    onClick={resetFilters}
                    title="Clear filters"
                    className="rounded-lg border border-slate-200 p-2.5 text-slate-500 hover:bg-slate-50"
                  >
                    <RefreshCw size={15} />
                  </button>
                </div>
              </div>

              {/* Errors */}
              {error && (
                <div
                  role="alert"
                  className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
                >
                  {error}
                </div>
              )}

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[950px] text-left">
                  <thead>
                    <tr className="bg-slate-50">
                      <th className="px-5 py-3 text-xs font-semibold text-slate-500">
                        Invoice
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Supplier
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Invoice date
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Due date
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Total amount
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Status
                      </th>

                      <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                        Actions
                      </th>
                    </tr>
                  </thead>

                  <tbody className="divide-y divide-slate-100">
                    {loading ? (
                      <tr>
                        <td colSpan={7} className="py-16 text-center">
                          <LoaderCircle
                            className="mx-auto animate-spin text-blue-600"
                            size={25}
                          />

                          <p className="mt-3 text-sm text-slate-500">
                            Loading invoices...
                          </p>
                        </td>
                      </tr>
                    ) : invoices.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="py-16 text-center">
                          <FileText
                            size={30}
                            className="mx-auto text-slate-300"
                          />

                          <p className="mt-3 text-sm font-semibold text-slate-700">
                            No invoices found
                          </p>

                          <p className="mt-1 text-xs text-slate-400">
                            Try changing your search or filters.
                          </p>
                        </td>
                      </tr>
                    ) : (
                      invoices.map((invoice) => (
                        <tr
                          key={invoice.id}
                          className="transition hover:bg-slate-50"
                        >
                          <td className="px-5 py-4">
                            <div className="text-sm font-semibold text-slate-800">
                              {invoice.invoice_number ||
                                invoice.document?.filename ||
                                "Unnumbered invoice"}
                            </div>

                            <div className="mt-1 text-xs text-slate-400">
                              {invoice.id.slice(0, 8)}
                            </div>
                          </td>

                          <td className="px-4 py-4 text-sm text-slate-600">
                            {invoice.vendor?.name ?? "Vendor not assigned"}
                          </td>

                          <td className="px-4 py-4 text-sm text-slate-500">
                            {formatDate(invoice.invoice_date)}
                          </td>

                          <td className="px-4 py-4 text-sm text-slate-500">
                            {formatDate(invoice.due_date)}
                          </td>

                          <td className="whitespace-nowrap px-4 py-4 text-sm font-semibold text-slate-800">
                            {formatAmount(
                              invoice.total_amount,
                              invoice.currency,
                            )}
                          </td>

                          <td className="px-4 py-4">
                            <StatusBadge status={invoice.status} />
                          </td>

                          {/* Actions */}
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              {invoice.status === "failed" && canQueueProcessing && (
                                <button
                                  type="button"
                                  disabled={queueingInvoiceId === invoice.id}
                                  onClick={() => handleRetryProcessing(invoice.id)}
                                  className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-blue-200 px-3 py-2 text-xs font-semibold text-blue-700 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {queueingInvoiceId === invoice.id ? (
                                    <LoaderCircle size={14} className="animate-spin" />
                                  ) : (
                                    <RefreshCw size={14} />
                                  )}

                                  {queueingInvoiceId === invoice.id
                                    ? "Queueing..."
                                    : "Retry"}
                                </button>
                              )}

                              <Link
                                href={`/invoices/${invoice.id}?organizationId=${encodeURIComponent(organizationId)}`}
                                className="inline-flex items-center whitespace-nowrap rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-700"
                              >
                                Review
                              </Link>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex flex-col justify-between gap-3 border-t border-slate-100 px-5 py-4 sm:flex-row sm:items-center">
                <p className="text-xs text-slate-500">
                  Showing {count === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}
                  {"–"}
                  {Math.min(page * PAGE_SIZE, count)} of {count} invoices
                </p>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={page <= 1 || loading}
                    onClick={() =>
                      setPage((current) => Math.max(1, current - 1))
                    }
                    className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <ArrowLeft size={14} />
                    Previous
                  </button>

                  <span className="px-2 text-xs text-slate-500">
                    Page {page} of {totalPages}
                  </span>

                  <button
                    type="button"
                    disabled={page >= totalPages || loading}
                    onClick={() =>
                      setPage((current) =>
                        Math.min(totalPages, current + 1),
                      )
                    }
                    className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Next
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            </section>
          </>
        )}
      </div>

      {/* Upload dialog */}
      {uploadOpen && (
        <InvoiceUploadDialog
          organizationId={organizationId}
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            setRefreshKey((current) => current + 1);
          }}
        />
      )}
    </main>
  </ProtectedRoute>
);


}

export default function InvoicesPage() {
  return (
    <ProtectedRoute>
      <InvoiceWorkspace />
    </ProtectedRoute>
  );
}
