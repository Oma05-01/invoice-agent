
"use client";

import Link from "next/link";
import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  FileText,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Wallet,
  X,
} from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { ProtectedRoute } from "@/components/protected-route";

import {
  createVendorPayment,
  fetchAccountingAccounts,
  fetchVendorPayments,
} from "@/lib/accounting";

import { fetchVendors, type Vendor } from "@/lib/invoices";

import type {
  AccountingAccount,
  VendorPayment,
  VendorPaymentStatus,
} from "@/types/accounting";

type PaymentStatusFilter = "all" | VendorPaymentStatus;

function getLocalDateValue(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

function formatAmount(amount: string, currency: string): string {
  const numericAmount = Number(amount);

  if (!Number.isFinite(numericAmount)) {
    return `${currency} ${amount}`;
  }

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency: currency || "NGN",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(numericAmount);
  } catch {
    return `${currency} ${numericAmount.toLocaleString("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

function formatDate(value: string | null): string {
  if (!value) return "—";

  const date = new Date(`${value.slice(0, 10)}T00:00:00`);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatRole(role: string): string {
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function getVendorName(vendor: VendorPayment["vendor"]): string {
  return vendor.display_name?.trim() || vendor.legal_name;
}

function getPaymentReference(payment: VendorPayment): string {
  return (
    payment.reference ||
    payment.journal_reference ||
    payment.id.slice(0, 8)
  );
}

const statusLabels: Record<VendorPaymentStatus, string> = {
  draft: "Draft",
  posted: "Posted",
  reversed: "Reversed",
};

const statusStyles: Record<VendorPaymentStatus, string> = {
  draft: "bg-amber-50 text-amber-700 ring-amber-600/20",
  posted: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  reversed: "bg-rose-50 text-rose-700 ring-rose-600/20",
};

function PaymentStatusBadge({
  status,
}: {
  status: VendorPaymentStatus;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusStyles[status]}`}
    >
      {statusLabels[status]}
    </span>
  );
}

function VendorPaymentsWorkspace() {
  const { user } = useAuth();

  const organizations = user?.organizations ?? [];

  const [selectedOrganizationId, setSelectedOrganizationId] =
    useState("");

  const organizationId =
    selectedOrganizationId || organizations[0]?.id || "";

  const activeOrganization = organizations.find(
    (organization) => organization.id === organizationId,
  );

  const role = activeOrganization?.role ?? "";

  const canCreatePayment = [
    "owner",
    "finance_admin",
    "finance_operator",
  ].includes(role);

  const [payments, setPayments] = useState<VendorPayment[]>([]);
  const [accounts, setAccounts] = useState<AccountingAccount[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);

  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] =
    useState<PaymentStatusFilter>("all");

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [saving, setSaving] = useState(false);

  const [vendorId, setVendorId] = useState("");
  const [paymentAccountId, setPaymentAccountId] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("NGN");
  const [paymentDate, setPaymentDate] = useState(getLocalDateValue);
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");

  // Load payments, accounts and vendors for the selected organisation.
  // Load payments, accounts and vendors for the selected organisation.
    useEffect(() => {
  if (!organizationId) return;

  const controller = new AbortController();
  let active = true;

  async function loadData() {
    try {
      const [paymentData, accountData, vendorData] =
        await Promise.all([
          fetchVendorPayments(
            organizationId,
            controller.signal,
          ),
          fetchAccountingAccounts(
            organizationId,
            controller.signal,
          ),
          fetchVendors(organizationId),
        ]);

      if (!active) return;

      setPayments(paymentData.payments);

      setAccounts(
        accountData.accounts.filter(
          (account) =>
            account.is_active &&
            account.account_type === "asset",
        ),
      );

      setVendors(vendorData.results);
    } catch (loadError) {
      if (!active || controller.signal.aborted) return;

      setError(
        loadError instanceof Error
          ? loadError.message
          : "Unable to load vendor payment data.",
      );
    } finally {
      if (active) setLoading(false);
    }
  }

  loadData();

  return () => {
    active = false;
    controller.abort();
  };
}, [organizationId, refreshKey]);

  const filteredPayments = useMemo(() => {
    const query = searchInput.trim().toLowerCase();

    return payments.filter((payment) => {
      const matchesStatus =
        statusFilter === "all" ||
        payment.status === statusFilter;

      const searchableValues = [
        getPaymentReference(payment),
        payment.vendor.legal_name,
        payment.vendor.display_name ?? "",
        payment.vendor.vendor_code ?? "",
        payment.payment_account.name,
        payment.payment_account.code,
      ];

      const matchesSearch =
        !query ||
        searchableValues.some((value) =>
          value.toLowerCase().includes(query),
        );

      return matchesStatus && matchesSearch;
    });
  }, [payments, searchInput, statusFilter]);

  const draftCount = payments.filter(
    (payment) => payment.status === "draft",
  ).length;

  const postedCount = payments.filter(
    (payment) => payment.status === "posted",
  ).length;

  const reversedCount = payments.filter(
    (payment) => payment.status === "reversed",
  ).length;

  function resetCreateForm() {
    setVendorId("");
    setPaymentAccountId("");
    setAmount("");
    setCurrency("NGN");
    setPaymentDate(getLocalDateValue());
    setReference("");
    setDescription("");
  }

  async function handleCreatePayment(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!organizationId) {
      setError("Select an organisation before creating a payment.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccessMessage("");

    try {
      const createdPayment = await createVendorPayment(
        organizationId,
        {
          vendor_id: vendorId,
          payment_account_id: paymentAccountId,
          amount: amount.trim(),
          currency: currency.trim().toUpperCase(),
          payment_date: paymentDate,
          reference: reference.trim(),
          description: description.trim(),
        },
      );

      setPayments((current) => [
        createdPayment,
        ...current,
      ]);

      setShowCreateDialog(false);
      resetCreateForm();

      setSuccessMessage(
        `Draft payment ${getPaymentReference(createdPayment)} was created successfully.`,
      );
    } catch (createError) {
      setError(
        createError instanceof Error
          ? createError.message
          : "Unable to create the vendor payment.",
      );
    } finally {
      setSaving(false);
    }
  }

  function changeOrganization(value: string) {
    setSelectedOrganizationId(value);
    setLoading(true);
    setSearchInput("");
    setStatusFilter("all");
    setSuccessMessage("");
    setError("");
    }

  function openCreateDialog() {
    setError("");
    setSuccessMessage("");
    resetCreateForm();
    setShowCreateDialog(true);
  }

  return (
    <ProtectedRoute>
      <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 xl:px-8">
            <div className="flex items-center gap-3">
              <Link
                href="/accounting"
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-50"
                aria-label="Back to accounting"
              >
                <ArrowLeft size={18} />
              </Link>

              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  Accounting / Payables
                </p>
                <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                  Vendor Payments
                </h1>
              </div>
            </div>

            {organizations.length > 0 && (
              <div className="min-w-[220px]">
                <label
                  htmlFor="payment-organization"
                  className="mb-1.5 block text-xs font-semibold text-slate-500"
                >
                  Organisation
                </label>

                <select
                  id="payment-organization"
                  value={organizationId}
                  onChange={(event) =>
                    changeOrganization(event.target.value)
                  }
                  className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500"
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
            )}
          </div>
        </header>

        <div className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 xl:p-8">
          {organizations.length === 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-6">
              <h2 className="font-semibold text-amber-900">
                No active organisation
              </h2>
              <p className="mt-2 text-sm text-amber-800">
                Your account does not currently have an active
                organisation membership.
              </p>
            </div>
          ) : (
            <>
              <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white px-5 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                    <Wallet size={19} />
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-800">
                      {activeOrganization?.name}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-400">
                      Your role: {formatRole(role)}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                    setLoading(true);
                    setError("");
                    setSuccessMessage("");
                    setRefreshKey((current) => current + 1);
                    }}
                    disabled={loading}
                    className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                  >
                    <RefreshCw
                      size={16}
                      className={loading ? "animate-spin" : ""}
                    />
                    Refresh
                  </button>

                  {canCreatePayment && (
                    <button
                      type="button"
                      onClick={openCreateDialog}
                      className="inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700"
                    >
                      <Plus size={17} />
                      Create payment
                    </button>
                  )}
                </div>
              </section>

              {error && (
                <div
                  role="alert"
                  className="mb-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
                >
                  <CircleAlert size={17} className="mt-0.5 shrink-0" />
                  <p>{error}</p>
                </div>
              )}

              {successMessage && (
                <div
                  role="status"
                  className="mb-5 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"
                >
                  <CheckCircle2 size={17} />
                  {successMessage}
                </div>
              )}

              <section className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  {
                    label: "All payments",
                    value: payments.length,
                    description: "Payments in this organisation",
                  },
                  {
                    label: "Draft",
                    value: draftCount,
                    description: "Awaiting allocation and posting",
                  },
                  {
                    label: "Posted",
                    value: postedCount,
                    description: "Successfully posted payments",
                  },
                  {
                    label: "Reversed",
                    value: reversedCount,
                    description: "Payments with posted reversals",
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
                  >
                    <p className="text-xs font-medium text-slate-500">
                      {item.label}
                    </p>
                    <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900">
                      {loading ? "—" : item.value}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {item.description}
                    </p>
                  </div>
                ))}
              </section>

              <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-5 py-5">
                  <div>
                    <h2 className="font-semibold text-slate-900">
                      Payment register
                    </h2>
                    <p className="mt-1 text-xs text-slate-400">
                      View and manage payments made to registered vendors.
                    </p>
                  </div>

                  <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                    <div className="relative min-w-[200px] flex-1 sm:flex-none">
                      <Search
                        size={16}
                        className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                      />
                      <input
                        type="search"
                        value={searchInput}
                        onChange={(event) =>
                          setSearchInput(event.target.value)
                        }
                        placeholder="Search payments..."
                        aria-label="Search payments"
                        className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-blue-500 sm:w-60"
                      />
                    </div>

                    <select
                      value={statusFilter}
                      onChange={(event) =>
                        setStatusFilter(
                          event.target.value as PaymentStatusFilter,
                        )
                      }
                      aria-label="Filter by payment status"
                      className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500"
                    >
                      <option value="all">All statuses</option>
                      <option value="draft">Draft</option>
                      <option value="posted">Posted</option>
                      <option value="reversed">Reversed</option>
                    </select>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-5 py-3.5 font-semibold">
                          Payment
                        </th>
                        <th className="px-5 py-3.5 font-semibold">
                          Vendor
                        </th>
                        <th className="px-5 py-3.5 font-semibold">
                          Payment account
                        </th>
                        <th className="px-5 py-3.5 font-semibold">
                          Amount
                        </th>
                        <th className="px-5 py-3.5 font-semibold">
                          Allocations
                        </th>
                        <th className="px-5 py-3.5 font-semibold">
                          Status
                        </th>
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-slate-100">
                      {loading ? (
                        <tr>
                          <td colSpan={6} className="px-5 py-16 text-center">
                            <LoaderCircle
                              size={22}
                              className="mx-auto animate-spin text-blue-600"
                            />
                            <p className="mt-3 text-sm text-slate-500">
                              Loading vendor payments...
                            </p>
                          </td>
                        </tr>
                      ) : filteredPayments.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="px-5 py-16 text-center">
                            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
                              <FileText size={22} />
                            </div>
                            <p className="mt-3 font-medium text-slate-700">
                              {payments.length === 0
                                ? "No vendor payments yet"
                                : "No matching payments"}
                            </p>
                            <p className="mt-1 text-xs text-slate-400">
                              {payments.length === 0
                                ? "Create a draft payment to get started."
                                : "Try changing your search or status filter."}
                            </p>
                          </td>
                        </tr>
                      ) : (
                        filteredPayments.map((payment) => (
                          <tr
                            key={payment.id}
                            className="transition hover:bg-slate-50/70"
                          >
                            <td className="px-5 py-4">
                              <Link
                                href={`/accounting/vendor-payments/${payment.id}`}
                                className="font-semibold text-blue-700 hover:text-blue-900 hover:underline"
                                >
                                {getPaymentReference(payment)}
                                </Link>
                              <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
                                <CalendarDays size={13} />
                                {formatDate(payment.payment_date)}
                              </p>
                            </td>

                            <td className="px-5 py-4">
                              <p className="font-medium text-slate-800">
                                {getVendorName(payment.vendor)}
                              </p>
                              <p className="mt-1 text-xs text-slate-400">
                                {payment.vendor.vendor_code || "No vendor code"}
                              </p>
                            </td>

                            <td className="px-5 py-4">
                              <p className="font-medium text-slate-700">
                                {payment.payment_account.name}
                              </p>
                              <p className="mt-1 text-xs text-slate-400">
                                {payment.payment_account.code}
                              </p>
                            </td>

                            <td className="px-5 py-4 font-semibold tabular-nums text-slate-900">
                              {formatAmount(
                                payment.amount,
                                payment.currency,
                              )}
                            </td>

                            <td className="px-5 py-4 text-slate-600">
                              {payment.allocations.length}
                              {payment.allocations.length === 1
                                ? " invoice"
                                : " invoices"}
                            </td>

                            <td className="px-5 py-4">
                              <PaymentStatusBadge
                                status={payment.status}
                              />
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-4">
                  <p className="text-xs text-slate-400">
                    Showing {filteredPayments.length} of {payments.length} payments
                  </p>
                  <p className="text-xs text-slate-400">
                    Payment records are restricted to the selected organisation.
                  </p>
                </div>
              </section>
            </>
          )}
        </div>

        {showCreateDialog && (
          <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/40 p-4">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="create-payment-title"
              className="my-8 w-full max-w-2xl rounded-2xl bg-white shadow-xl"
            >
              <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5">
                <div>
                  <h2
                    id="create-payment-title"
                    className="text-lg font-bold text-slate-900"
                  >
                    Create vendor payment
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Create a draft payment before allocating it to invoices.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setShowCreateDialog(false)}
                  disabled={saving}
                  aria-label="Close dialog"
                  className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
                >
                  <X size={19} />
                </button>
              </div>

              <form onSubmit={handleCreatePayment}>
                <div className="grid gap-5 px-6 py-6 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label
                      htmlFor="payment-vendor"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Vendor
                    </label>
                    <select
                      id="payment-vendor"
                      value={vendorId}
                      onChange={(event) => setVendorId(event.target.value)}
                      required
                      disabled={saving || vendors.length === 0}
                      className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 disabled:bg-slate-50"
                    >
                      <option value="">Select a vendor</option>
                      {vendors.map((vendor) => (
                        <option key={vendor.id} value={vendor.id}>
                          {vendor.display_name || vendor.legal_name}
                          {vendor.vendor_code
                            ? ` (${vendor.vendor_code})`
                            : ""}
                        </option>
                      ))}
                    </select>
                    {vendors.length === 0 && (
                      <p className="mt-1.5 text-xs text-amber-700">
                        No vendors are available for this organisation.
                      </p>
                    )}
                  </div>

                  <div className="sm:col-span-2">
                    <label
                      htmlFor="payment-account"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Payment account
                    </label>
                    <select
                      id="payment-account"
                      value={paymentAccountId}
                      onChange={(event) =>
                        setPaymentAccountId(event.target.value)
                      }
                      required
                      disabled={saving || accounts.length === 0}
                      className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500 disabled:bg-slate-50"
                    >
                      <option value="">Select an asset account</option>
                      {accounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.code} — {account.name}
                        </option>
                      ))}
                    </select>
                    {accounts.length === 0 && (
                      <p className="mt-1.5 text-xs text-amber-700">
                        No active asset accounts are available. Check the organisation chart of accounts.
                      </p>
                    )}
                  </div>

                  <div>
                    <label
                      htmlFor="payment-amount"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Amount
                    </label>
                    <input
                      id="payment-amount"
                      type="number"
                      min="0.01"
                      step="0.01"
                      required
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="0.00"
                      disabled={saving}
                      className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="payment-currency"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Currency
                    </label>
                    <input
                      id="payment-currency"
                      type="text"
                      minLength={3}
                      maxLength={3}
                      required
                      value={currency}
                      onChange={(event) =>
                        setCurrency(
                          event.target.value
                            .replace(/[^a-zA-Z]/g, "")
                            .toUpperCase()
                            .slice(0, 3),
                        )
                      }
                      placeholder="NGN"
                      disabled={saving}
                      className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm uppercase outline-none focus:border-blue-500"
                    />
                    <p className="mt-1 text-xs text-slate-400">
                      Enter a three-letter currency code.
                    </p>
                  </div>

                  <div>
                    <label
                      htmlFor="payment-date"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Payment date
                    </label>
                    <input
                      id="payment-date"
                      type="date"
                      required
                      value={paymentDate}
                      onChange={(event) =>
                        setPaymentDate(event.target.value)
                      }
                      disabled={saving}
                      className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="payment-reference"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Payment reference
                    </label>
                    <input
                      id="payment-reference"
                      type="text"
                      maxLength={100}
                      value={reference}
                      onChange={(event) =>
                        setReference(event.target.value)
                      }
                      placeholder="e.g. BANK-TRANSFER-001"
                      disabled={saving}
                      className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
                    />
                  </div>

                  <div className="sm:col-span-2">
                    <label
                      htmlFor="payment-description"
                      className="mb-1.5 block text-sm font-medium text-slate-700"
                    >
                      Description
                      <span className="ml-1 font-normal text-slate-400">
                        (optional)
                      </span>
                    </label>
                    <textarea
                      id="payment-description"
                      rows={3}
                      maxLength={500}
                      value={description}
                      onChange={(event) =>
                        setDescription(event.target.value)
                      }
                      placeholder="Add a short description for this payment..."
                      disabled={saving}
                      className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-6 py-5">
                  <button
                    type="button"
                    onClick={() => setShowCreateDialog(false)}
                    disabled={saving}
                    className="h-10 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    disabled={
                      saving ||
                      vendors.length === 0 ||
                      accounts.length === 0
                    }
                    className="inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saving && (
                      <LoaderCircle size={16} className="animate-spin" />
                    )}
                    {saving ? "Creating..." : "Create draft payment"}
                  </button>
                </div>
              </form>
            </section>
          </div>
        )}
      </main>
    </ProtectedRoute>
  );
}

export default function VendorPaymentsPage() {
  return (
    <ProtectedRoute>
      <VendorPaymentsWorkspace />
    </ProtectedRoute>
  );
}
