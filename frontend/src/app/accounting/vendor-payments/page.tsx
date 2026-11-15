"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  FileText,
  LoaderCircle,
  RefreshCw,
  Trash2,
  Wallet,
} from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { ProtectedRoute } from "@/components/protected-route";
import {
  allocateInvoiceToVendorPayment,
  fetchAPAgeingReport,
  fetchVendorPayment,
  removeVendorPaymentAllocation,
  postVendorPayment,
  reverseVendorPayment,
} from "@/lib/accounting";
import type {
  APAgeingInvoice,
  JournalEntry,
  VendorPayment,
  VendorPaymentStatus,
} from "@/types/accounting";
type AllocationCandidate = APAgeingInvoice;
type PendingAllocationRemoval = {
  invoiceId: string;
  invoiceNumber: string;
  amount: string;
};
function normalizeIntegerString(value: string): string {
  return value.replace(/^0+(?=\d)/, "") || "0";
}
// Convert a monetary decimal string into integer minor units.
// Calculations use strings so large monetary values do not lose
// precision through JavaScript floating-point arithmetic.
function toMinorUnits(value: string): string {
  const trimmed = value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) {
    return "0";
  }
  const [whole, fraction = ""] = trimmed.split(".");
  return normalizeIntegerString(
    `${whole}${fraction.padEnd(2, "0")}`,
  );
}
function compareMinorUnits(left: string, right: string): number {
  const a = normalizeIntegerString(left);
  const b = normalizeIntegerString(right);
  if (a.length !== b.length) {
    return a.length > b.length ? 1 : -1;
  }
  if (a === b) return 0;
  return a > b ? 1 : -1;
}
function addMinorUnits(left: string, right: string): string {
  let i = left.length - 1;
  let j = right.length - 1;
  let carry = 0;
  let result = "";
  while (i >= 0 || j >= 0 || carry > 0) {
    const a = i >= 0 ? Number(left[i]) : 0;
    const b = j >= 0 ? Number(right[j]) : 0;
    const sum = a + b + carry;
    result = String(sum % 10) + result;
    carry = Math.floor(sum / 10);
    i -= 1;
    j -= 1;
  }
  return normalizeIntegerString(result);
}
// Subtract two unsigned integer strings. The caller must ensure
// that the first value is greater than or equal to the second.
function subtractAbsolute(left: string, right: string): string {
  let i = left.length - 1;
  let j = right.length - 1;
  let borrow = 0;
  let result = "";
  while (i >= 0) {
    let a = Number(left[i]) - borrow;
    const b = j >= 0 ? Number(right[j]) : 0;
    borrow = 0;
    if (a < b) {
      a += 10;
      borrow = 1;
    }
    result = String(a - b) + result;
    i -= 1;
    j -= 1;
  }
  return normalizeIntegerString(result);
}
function subtractMinorUnits(left: string, right: string): string {
  const comparison = compareMinorUnits(left, right);
  if (comparison >= 0) {
    return subtractAbsolute(left, right);
  }
  return `-${subtractAbsolute(right, left)}`;
}
function sumAmounts(values: string[]): string {
  return values.reduce(
    (total, value) =>
      addMinorUnits(total, toMinorUnits(value)),
    "0",
  );
}
function minorUnitsToDecimal(value: string): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const padded = unsigned.padStart(3, "0");
  const whole = padded.slice(0, -2);
  const fraction = padded.slice(-2);
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}
function formatAmount(value: string, currency: string): string {
  const numericAmount = Number(value);
  if (!Number.isFinite(numericAmount)) {
    return `${currency} ${value}`;
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
const statusLabels: Record<VendorPaymentStatus, string> = {
  draft: "Draft",
  posted: "Posted",
  reversed: "Reversed",
};
const statusStyles: Record<VendorPaymentStatus, string> = {
  draft: "bg-amber-50 text-amber-700",
  posted: "bg-emerald-50 text-emerald-700",
  reversed: "bg-rose-50 text-rose-700",
};
function VendorPaymentDetailWorkspace() {
  const params = useParams<{ paymentId: string }>();
  const paymentId = params.paymentId;
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
  const canPostOrReverse = [
    "owner",
    "finance_admin",
  ].includes(role);
  const canManageAllocations = [
    "owner",
    "finance_admin",
    "finance_operator",
  ].includes(role);
  const [payment, setPayment] = useState<VendorPayment | null>(null);
  const [candidateInvoices, setCandidateInvoices] =
    useState<AllocationCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [allocationError, setAllocationError] = useState("");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState("");
  const [allocationAmount, setAllocationAmount] = useState("");
  const [savingAllocation, setSavingAllocation] = useState(false);
  const [removingInvoiceId, setRemovingInvoiceId] = useState("");
  const [allocationToRemove, setAllocationToRemove] =
    useState<PendingAllocationRemoval | null>(null);
  const [allocationRemovalError, setAllocationRemovalError] =
    useState("");
  const [confirmationAction, setConfirmationAction] =
    useState<"post" | "reverse" | null>(null);
  const [reversalReason, setReversalReason] = useState("");
  const [processingAction, setProcessingAction] = useState(false);
  const [reversalJournal, setReversalJournal] =
    useState<JournalEntry | null>(null);
async function refreshCandidateInvoices(
  paymentRecord: VendorPayment,
) {
  const ageingData = await fetchAPAgeingReport(
    organizationId,
    {
      currency: paymentRecord.currency,
    },
  );
  const currencyReport = ageingData.currencies.find(
    (item) => item.currency === paymentRecord.currency,
  );
  const vendorReport = currencyReport?.vendors.find(
    (vendor) => vendor.vendor_id === paymentRecord.vendor_id,
  );
  setCandidateInvoices(vendorReport?.invoices ?? []);
}
async function handleConfirmPaymentAction(
  event: FormEvent<HTMLFormElement>,
) {
  event.preventDefault();
  if (!payment || !confirmationAction) return;
  if (
    confirmationAction === "post" &&
    !isFullyAllocated
  ) {
    setError(
      "The payment must be fully allocated before posting.",
    );
    return;
  }
  if (
    confirmationAction === "reverse" &&
    !reversalReason.trim()
  ) {
    setError("A reversal reason is required.");
    return;
  }
  setProcessingAction(true);
  setError("");
  setSuccessMessage("");
  try {
    if (confirmationAction === "post") {
      const updatedPayment = await postVendorPayment(
        organizationId,
        payment.id,
      );
      setPayment(updatedPayment);
      setReversalJournal(null);
      setConfirmationAction(null);
      setSuccessMessage(
        `Payment ${updatedPayment.reference || updatedPayment.id} was posted successfully.`,
      );
      try {
        await refreshCandidateInvoices(updatedPayment);
      } catch {
        setError(
          "The payment was posted, but the AP ageing candidates could not be refreshed. Use Refresh to reload them.",
        );
      }
    } else {
      const result = await reverseVendorPayment(
        organizationId,
        payment.id,
        {
          reversal_reason: reversalReason.trim(),
        },
      );
      setPayment(result.payment);
      setReversalJournal(result.reversal_journal);
      setConfirmationAction(null);
      setReversalReason("");
      setSuccessMessage(
        `Payment ${result.payment.reference || result.payment.id} was reversed successfully.`,
      );
      try {
        await refreshCandidateInvoices(result.payment);
      } catch {
        setError(
          "The payment was reversed, but the AP ageing candidates could not be refreshed. Use Refresh to reload them.",
        );
      }
    }
  } catch (actionError) {
    setError(
      actionError instanceof Error
        ? actionError.message
        : "The payment action could not be completed.",
    );
  } finally {
    setProcessingAction(false);
  }
}
  // Retrieve the payment and its vendor's outstanding AP invoices.
  useEffect(() => {
    if (!organizationId || !paymentId) return;
    const controller = new AbortController();
    let active = true;
    async function loadData() {
      try {
        const paymentData = await fetchVendorPayment(
          organizationId,
          paymentId,
          controller.signal,
        );
        const ageingData = await fetchAPAgeingReport(
          organizationId,
          {
            currency: paymentData.currency,
          },
        );
        if (!active) return;
        const currencyReport = ageingData.currencies.find(
          (item) => item.currency === paymentData.currency,
        );
        const vendorReport = currencyReport?.vendors.find(
          (vendor) => vendor.vendor_id === paymentData.vendor_id,
        );
        setPayment(paymentData);
        setCandidateInvoices(vendorReport?.invoices ?? []);
      } catch (loadError) {
        if (!active || controller.signal.aborted) return;
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Unable to load vendor payment details.",
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
  }, [organizationId, paymentId, refreshKey]);
  const allocations = useMemo(
    () => payment?.allocations ?? [],
    [payment?.allocations],
    );
  const totalAllocated = useMemo(
    () => sumAmounts(allocations.map((item) => item.amount)),
    [allocations],
  );
  const paymentAmount = payment
    ? toMinorUnits(payment.amount)
    : "0";
  const remainingAmount = subtractMinorUnits(
    paymentAmount,
    totalAllocated,
  );
  const isFullyAllocated =
    paymentAmount !== "0" &&
    compareMinorUnits(totalAllocated, paymentAmount) === 0;
  const selectedInvoice = candidateInvoices.find(
    (invoice) => invoice.invoice_id === selectedInvoiceId,
  );
  const existingAllocation = allocations.find(
    (item) => item.invoice_id === selectedInvoiceId,
  );
  const existingAllocationAmount = existingAllocation
    ? toMinorUnits(existingAllocation.amount)
    : "0";
  const availablePaymentAmount = addMinorUnits(
    remainingAmount.startsWith("-") ? "0" : remainingAmount,
    existingAllocationAmount,
  );
  const allocationIsEditable =
    payment?.status === "draft" && canManageAllocations;
  const currentReference =
    payment?.reference ||
    payment?.journal_reference ||
    payment?.id.slice(0, 8) ||
    "";
  function handleInvoiceSelection(invoiceId: string) {
    setSelectedInvoiceId(invoiceId);
    setError("");
    setAllocationError("");
    setAllocationAmount("");
    const existing = allocations.find(
      (item) => item.invoice_id === invoiceId,
    );
    if (existing) {
      setAllocationAmount(existing.amount);
    }
  }
  async function handleSaveAllocation(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!payment || !selectedInvoice) return;
    const amountValue = allocationAmount.trim();
    if (!/^\d+(\.\d{1,2})?$/.test(amountValue)) {
      setAllocationError(
        "Enter a valid amount with no more than two decimal places.",
      );
      return;
    }
    const requestedAmount = toMinorUnits(amountValue);
    const invoiceOutstanding = toMinorUnits(
      selectedInvoice.outstanding_amount,
    );
    if (requestedAmount === "0") {
      setAllocationError(
        "Allocation amount must be greater than zero.",
      );
      return;
    }
    if (
      compareMinorUnits(
        requestedAmount,
        availablePaymentAmount,
      ) > 0
    ) {
      setAllocationError(
        "The allocation exceeds the remaining available payment amount.",
      );
      return;
    }
    if (
      compareMinorUnits(
        requestedAmount,
        invoiceOutstanding,
      ) > 0
    ) {
      setAllocationError(
        "The allocation exceeds the invoice's reported outstanding AP balance.",
      );
      return;
    }
    setSavingAllocation(true);
    setError("");
    setAllocationError("");
    setSuccessMessage("");
    try {
      const result = await allocateInvoiceToVendorPayment(
        organizationId,
        payment.id,
        {
          invoice_id: selectedInvoice.invoice_id,
          amount: amountValue,
        },
      );
      setPayment((current) => {
        if (!current) return current;
        const updatedAllocations = [
          ...current.allocations.filter(
            (item) => item.invoice_id !== result.invoice_id,
          ),
          result,
        ].sort((a, b) =>
          a.invoice_number.localeCompare(b.invoice_number),
        );
        return {
          ...current,
          allocations: updatedAllocations,
        };
      });
      setSelectedInvoiceId("");
      setAllocationAmount("");
      setSuccessMessage(
        existingAllocation
          ? `Allocation for ${result.invoice_number} was updated.`
          : `Invoice ${result.invoice_number} was allocated successfully.`,
      );
    } catch (saveError) {
      setAllocationError(
        saveError instanceof Error
          ? saveError.message
          : "Unable to save the invoice allocation.",
      );
    } finally {
      setSavingAllocation(false);
    }
  }
  function requestRemoveAllocation(
    invoiceId: string,
    invoiceNumber: string,
  ) {
    if (!payment || removingInvoiceId) return;
    const allocation = allocations.find(
      (item) => item.invoice_id === invoiceId,
    );
    if (!allocation) return;
    setError("");
    setAllocationError("");
    setAllocationRemovalError("");
    setAllocationToRemove({
      invoiceId,
      invoiceNumber,
      amount: allocation.amount,
    });
  }
  async function handleConfirmRemoveAllocation() {
    if (!payment || !allocationToRemove || removingInvoiceId) return;
    const { invoiceId, invoiceNumber } = allocationToRemove;
    setRemovingInvoiceId(invoiceId);
    setAllocationRemovalError("");
    setError("");
    setSuccessMessage("");
    try {
      await removeVendorPaymentAllocation(
        organizationId,
        payment.id,
        invoiceId,
      );
      setPayment((current) =>
        current
          ? {
              ...current,
              allocations: current.allocations.filter(
                (item) => item.invoice_id !== invoiceId,
              ),
            }
          : current,
      );
      if (selectedInvoiceId === invoiceId) {
        setSelectedInvoiceId("");
        setAllocationAmount("");
      }
      setAllocationToRemove(null);
      setSuccessMessage(
        `Allocation for ${invoiceNumber} was removed.`,
      );
    } catch (removeError) {
      setAllocationRemovalError(
        removeError instanceof Error
          ? removeError.message
          : "Unable to remove the invoice allocation.",
      );
    } finally {
      setRemovingInvoiceId("");
    }
  }
  function changeOrganization(value: string) {
    setSelectedOrganizationId(value);
    setAllocationToRemove(null);
    setAllocationRemovalError("");
    setPayment(null);
    setCandidateInvoices([]);
    setLoading(true);
    setError("");
    setSuccessMessage("");
    setSelectedInvoiceId("");
    setAllocationAmount("");
  }
  function refreshPayment() {
    setLoading(true);
    setError("");
    setSuccessMessage("");
    setRefreshKey((current) => current + 1);
  }
  return (
    <ProtectedRoute>
      <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 xl:px-8">
            <div className="flex items-center gap-3">
              <Link
                href="/accounting/vendor-payments"
                className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-50"
                aria-label="Back to vendor payments"
              >
                <ArrowLeft size={18} />
              </Link>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  Accounting / Payables / Vendor Payments
                </p>
                <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                  Payment details
                </h1>
              </div>
            </div>
            {organizations.length > 0 && (
              <div className="min-w-[220px]">
                <label
                  htmlFor="detail-organization"
                  className="mb-1.5 block text-xs font-semibold text-slate-500"
                >
                  Organisation
                </label>
                <select
                  id="detail-organization"
                  value={organizationId}
                  onChange={(event) =>
                    changeOrganization(event.target.value)
                  }
                  className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
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
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800">
              Your account does not currently have an active organisation membership.
            </div>
          ) : (
            <>
              <section className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-5">
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
                {canPostOrReverse && payment?.status === "draft" && (
                    <button
                    type="button"
                    onClick={() => {
                        setError("");
                        setConfirmationAction("post");
                    }}
                    disabled={!isFullyAllocated || processingAction}
                    title={
                        isFullyAllocated
                        ? "Post this fully allocated payment"
                        : "Allocate the entire payment before posting"
                    }
                    className="inline-flex h-10 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                    <CheckCircle2 size={16} />
                    Post payment
                    </button>
                )}
                {canPostOrReverse && payment?.status === "posted" && (
                    <button
                    type="button"
                    onClick={() => {
                        setError("");
                        setReversalReason("");
                        setConfirmationAction("reverse");
                    }}
                    disabled={processingAction}
                    className="inline-flex h-10 items-center gap-2 rounded-lg border border-rose-200 bg-white px-4 text-sm font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-50"
                    >
                    <CircleAlert size={16} />
                    Reverse payment
                    </button>
                )}
                <button
                    type="button"
                    onClick={refreshPayment}
                    disabled={loading || processingAction}
                    className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                    <RefreshCw
                    size={16}
                    className={loading ? "animate-spin" : ""}
                    />
                    Refresh
                </button>
                </div>
                {canPostOrReverse &&
                payment?.status === "draft" &&
                !isFullyAllocated && (
                    <p className="mt-3 text-xs text-amber-700">
                    Posting is unavailable until the total invoice allocations
                    equal the payment amount exactly.
                    </p>
                )}
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
              {loading ? (
                <div className="rounded-xl border border-slate-200 bg-white py-20 text-center">
                  <LoaderCircle
                    size={24}
                    className="mx-auto animate-spin text-blue-600"
                  />
                  <p className="mt-3 text-sm text-slate-500">
                    Loading payment details...
                  </p>
                </div>
              ) : payment ? (
                <>
                  <section className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-xl border border-slate-200 bg-white p-5">
                      <p className="text-xs font-medium text-slate-500">
                        Payment reference
                      </p>
                      <p className="mt-2 break-all font-semibold text-slate-900">
                        {currentReference}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white p-5">
                      <p className="text-xs font-medium text-slate-500">
                        Vendor
                      </p>
                      <p className="mt-2 font-semibold text-slate-900">
                        {payment.vendor.display_name ||
                          payment.vendor.legal_name}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {payment.vendor.vendor_code || "No vendor code"}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white p-5">
                      <p className="text-xs font-medium text-slate-500">
                        Payment amount
                      </p>
                      <p className="mt-2 font-semibold text-slate-900">
                        {formatAmount(payment.amount, payment.currency)}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {formatDate(payment.payment_date)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white p-5">
                      <p className="text-xs font-medium text-slate-500">
                        Payment status
                      </p>
                      <span
                        className={`mt-2 inline-flex rounded-full px-3 py-1 text-xs font-semibold ${statusStyles[payment.status]}`}
                      >
                        {statusLabels[payment.status]}
                      </span>
                      <p className="mt-1 text-xs text-slate-400">
                        Journal: {payment.journal_status || "Unavailable"}
                      </p>
                    </div>
                  </section>
                  {reversalJournal && (
                    <section className="mb-6 rounded-xl border border-rose-200 bg-rose-50 p-5">
                        <h2 className="font-semibold text-rose-900">
                        Reversal journal created
                        </h2>
                        <div className="mt-3 grid gap-3 sm:grid-cols-3">
                        <div>
                            <p className="text-xs text-rose-700">Journal reference</p>
                            <p className="mt-1 text-sm font-semibold text-rose-950">
                            {reversalJournal.reference}
                            </p>
                        </div>
                        <div>
                            <p className="text-xs text-rose-700">Journal status</p>
                            <p className="mt-1 text-sm font-semibold text-rose-950">
                            {reversalJournal.status}
                            </p>
                        </div>
                        <div>
                            <p className="text-xs text-rose-700">Entry date</p>
                            <p className="mt-1 text-sm font-semibold text-rose-950">
                            {formatDate(reversalJournal.entry_date)}
                            </p>
                        </div>
                        </div>
                    </section>
                    )}
                  <section className="mb-6 rounded-xl border border-slate-200 bg-white p-5">
                    <div className="grid gap-5 sm:grid-cols-3">
                      <div>
                        <p className="text-xs font-medium text-slate-500">
                          Total payment
                        </p>
                        <p className="mt-2 text-xl font-bold text-slate-900">
                          {formatAmount(payment.amount, payment.currency)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-slate-500">
                          Total allocated
                        </p>
                        <p className="mt-2 text-xl font-bold text-slate-900">
                          {formatAmount(
                            minorUnitsToDecimal(totalAllocated),
                            payment.currency,
                          )}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-medium text-slate-500">
                          Unallocated amount
                        </p>
                        <p className="mt-2 text-xl font-bold text-blue-700">
                          {formatAmount(
                            minorUnitsToDecimal(remainingAmount),
                            payment.currency,
                          )}
                        </p>
                      </div>
                    </div>
                    <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-blue-600 transition-all"
                        style={{
                          width: `${Math.min(
                            100,
                            paymentAmount === "0"
                              ? 0
                              : (Number(totalAllocated) /
                                  Number(paymentAmount)) *
                                  100,
                          )}%`,
                        }}
                      />
                    </div>
                  </section>
                  <section className="mb-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
                    <div className="border-b border-slate-100 px-5 py-5">
                      <h2 className="font-semibold text-slate-900">
                        Invoice allocations
                      </h2>
                      <p className="mt-1 text-xs text-slate-400">
                        Invoices currently assigned to this vendor payment.
                      </p>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[600px] text-left text-sm">
                        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                          <tr>
                            <th className="px-5 py-3 font-semibold">
                              Invoice
                            </th>
                            <th className="px-5 py-3 font-semibold">
                              Allocation date
                            </th>
                            <th className="px-5 py-3 font-semibold">
                              Allocated amount
                            </th>
                            <th className="px-5 py-3 font-semibold">
                              Actions
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {allocations.length === 0 ? (
                            <tr>
                              <td
                                colSpan={4}
                                className="px-5 py-12 text-center"
                              >
                                <FileText
                                  size={22}
                                  className="mx-auto text-slate-300"
                                />
                                <p className="mt-3 font-medium text-slate-700">
                                  No invoice allocations
                                </p>
                                <p className="mt-1 text-xs text-slate-400">
                                  This payment has not been assigned to any invoices.
                                </p>
                              </td>
                            </tr>
                          ) : (
                            allocations.map((allocation) => (
                              <tr key={allocation.id}>
                                <td className="px-5 py-4 font-medium text-slate-800">
                                  {allocation.invoice_number}
                                </td>
                                <td className="px-5 py-4 text-slate-500">
                                  {formatDate(
                                    allocation.created_at,
                                  )}
                                </td>
                                <td className="px-5 py-4 font-semibold tabular-nums text-slate-900">
                                  {formatAmount(
                                    allocation.amount,
                                    payment.currency,
                                  )}
                                </td>
                                <td className="px-5 py-4">
                                  {allocationIsEditable && (
                                    <div className="flex items-center gap-2">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          handleInvoiceSelection(
                                            allocation.invoice_id,
                                          )
                                        }
                                        className="text-xs font-semibold text-blue-700 hover:underline"
                                      >
                                        Edit
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          requestRemoveAllocation(
                                            allocation.invoice_id,
                                            allocation.invoice_number,
                                          )
                                        }
                                        disabled={
                                          removingInvoiceId ===
                                          allocation.invoice_id
                                        }
                                        aria-label={`Remove allocation for ${allocation.invoice_number}`}
                                        className="inline-flex items-center gap-1 text-xs font-semibold text-rose-600 hover:underline disabled:opacity-50"
                                      >
                                        {removingInvoiceId ===
                                        allocation.invoice_id ? (
                                          <LoaderCircle
                                            size={13}
                                            className="animate-spin"
                                          />
                                        ) : (
                                          <Trash2 size={13} />
                                        )}
                                        Remove
                                      </button>
                                    </div>
                                  )}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </section>
                  {allocationIsEditable && (
                    <section className="rounded-xl border border-slate-200 bg-white p-5">
                      <div className="mb-5">
                        <h2 className="font-semibold text-slate-900">
                          {existingAllocation
                            ? "Update invoice allocation"
                            : "Allocate an invoice"}
                        </h2>
                        <p className="mt-1 text-xs text-slate-400">
                          Only outstanding invoices for this vendor and payment currency are shown.
                        </p>
                      </div>
                      {allocationError && (
                        <div
                          role="alert"
                          className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
                        >
                          <CircleAlert size={16} className="mt-0.5 shrink-0" />
                          <p>{allocationError}</p>
                        </div>
                      )}
                      {candidateInvoices.length === 0 ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                          No outstanding invoices were found for this vendor in {payment.currency}.
                        </div>
                      ) : (
                        <form
                          onSubmit={handleSaveAllocation}
                          className="grid gap-4 md:grid-cols-[2fr_1fr_auto]"
                        >
                          <div>
                            <label
                              htmlFor="allocation-invoice"
                              className="mb-1.5 block text-sm font-medium text-slate-700"
                            >
                              Invoice
                            </label>
                            <select
                              id="allocation-invoice"
                              value={selectedInvoiceId}
                              onChange={(event) =>
                                handleInvoiceSelection(
                                  event.target.value,
                                )
                              }
                              required
                              disabled={savingAllocation}
                              className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                            >
                              <option value="">
                                Select an outstanding invoice
                              </option>
                              {candidateInvoices.map((invoice) => {
                                const isAllocated = allocations.some(
                                  (allocation) =>
                                    allocation.invoice_id ===
                                    invoice.invoice_id,
                                );
                                return (
                                  <option
                                    key={invoice.invoice_id}
                                    value={invoice.invoice_id}
                                  >
                                    {invoice.invoice_number}
                                    {isAllocated ? " (Already allocated)" : ""}
                                    {" — Outstanding: "}
                                    {formatAmount(
                                      invoice.outstanding_amount,
                                      payment.currency,
                                    )}
                                  </option>
                                );
                              })}
                            </select>
                            {selectedInvoice && (
                              <p className="mt-1.5 text-xs text-slate-500">
                                Reported AP outstanding:{" "}
                                {formatAmount(
                                  selectedInvoice.outstanding_amount,
                                  payment.currency,
                                )}
                              </p>
                            )}
                          </div>
                          <div>
                            <label
                              htmlFor="allocation-amount"
                              className="mb-1.5 block text-sm font-medium text-slate-700"
                            >
                              Allocation amount
                            </label>
                            <input
                              id="allocation-amount"
                              type="number"
                              min="0.01"
                              step="0.01"
                              required
                              value={allocationAmount}
                              onChange={(event) => {
                                setAllocationAmount(event.target.value);
                                setAllocationError("");
                              }}
                              disabled={savingAllocation}
                              placeholder="0.00"
                              className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-500"
                            />
                          </div>
                          <div className="flex items-end">
                            <button
                              type="submit"
                              disabled={
                                savingAllocation ||
                                !selectedInvoiceId ||
                                remainingAmount.startsWith("-") ||
                                availablePaymentAmount === "0"
                              }
                              className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 md:w-auto"
                            >
                              {savingAllocation && (
                                <LoaderCircle
                                  size={16}
                                  className="animate-spin"
                                />
                              )}
                              {savingAllocation
                                ? "Saving..."
                                : existingAllocation
                                  ? "Update allocation"
                                  : "Allocate invoice"}
                            </button>
                          </div>
                        </form>
                      )}
                      <div className="mt-5 rounded-lg bg-slate-50 p-4 text-xs leading-relaxed text-slate-500">
                        The AP ageing report supplies candidate invoices and their posted-basis outstanding balances. The accounting backend performs the authoritative checks for approval, posted journal status, currency, invoice balance and allocations reserved by other draft payments. Draft allocations do not reduce reported AP.
                      </div>
                    </section>
                  )}
                  {!allocationIsEditable && (
                    <section className="rounded-xl border border-slate-200 bg-slate-50 p-5">
                      <p className="text-sm font-medium text-slate-700">
                        Allocations are read-only.
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {payment.status !== "draft"
                          ? "Only draft payments can have their allocations changed."
                          : "Your organisation role does not permit allocation changes."}
                      </p>
                    </section>
                  )}
                </>
              ) : (
                <section className="rounded-xl border border-slate-200 bg-white p-10 text-center">
                  <CircleAlert
                    size={24}
                    className="mx-auto text-slate-400"
                  />
                  <p className="mt-3 font-semibold text-slate-800">
                    Payment unavailable
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    The payment could not be found or accessed in this organisation.
                  </p>
                  <Link
                    href="/accounting/vendor-payments"
                    className="mt-4 inline-flex text-sm font-semibold text-blue-700 hover:underline"
                  >
                    Return to payment register
                  </Link>
                </section>
              )}
            </>
          )}
        </div>
        {confirmationAction && payment && (
            <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/40 p-4">
                <section
                role="dialog"
                aria-modal="true"
                aria-labelledby="payment-action-title"
                className="my-8 w-full max-w-lg rounded-2xl bg-white shadow-xl"
                >
                <form onSubmit={handleConfirmPaymentAction}>
                    <div className="border-b border-slate-100 px-6 py-5">
                    <div className="flex items-center gap-3">
                        <div
                        className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                            confirmationAction === "post"
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-rose-50 text-rose-700"
                        }`}
                        >
                        {confirmationAction === "post" ? (
                            <CheckCircle2 size={20} />
                        ) : (
                            <CircleAlert size={20} />
                        )}
                        </div>
                        <div>
                        <h2
                            id="payment-action-title"
                            className="font-bold text-slate-900"
                        >
                            {confirmationAction === "post"
                            ? "Confirm payment posting"
                            : "Confirm payment reversal"}
                        </h2>
                        <p className="mt-1 text-xs text-slate-500">
                            {currentReference}
                        </p>
                        </div>
                    </div>
                    </div>
                    <div className="space-y-4 px-6 py-6">
                    <div className="rounded-lg bg-slate-50 p-4">
                        <div className="flex justify-between gap-3 text-sm">
                        <span className="text-slate-500">Vendor</span>
                        <span className="font-medium text-slate-800">
                            {payment.vendor.display_name ||
                            payment.vendor.legal_name}
                        </span>
                        </div>
                        <div className="mt-3 flex justify-between gap-3 text-sm">
                        <span className="text-slate-500">Payment amount</span>
                        <span className="font-semibold text-slate-900">
                            {formatAmount(payment.amount, payment.currency)}
                        </span>
                        </div>
                        <div className="mt-3 flex justify-between gap-3 text-sm">
                        <span className="text-slate-500">Allocated amount</span>
                        <span className="font-semibold text-slate-900">
                            {formatAmount(
                            minorUnitsToDecimal(totalAllocated),
                            payment.currency,
                            )}
                        </span>
                        </div>
                    </div>
                    {confirmationAction === "post" ? (
                        <p className="text-sm leading-relaxed text-slate-600">
                        You are about to post this vendor payment. Its
                        accounting journal will be posted and the allocated
                        amount will reduce the vendor&apos;s outstanding
                        Accounts Payable balance. This action cannot be
                        edited after posting; a reversal will be required
                        to undo it.
                        </p>
                    ) : (
                        <>
                        <p className="text-sm leading-relaxed text-slate-600">
                            A reversal journal will be created for this
                            posted payment. The original payment and its
                            allocations will remain in the audit history.
                        </p>
                        <div>
                            <label
                            htmlFor="payment-reversal-reason"
                            className="mb-1.5 block text-sm font-medium text-slate-700"
                            >
                            Reversal reason
                            </label>
                            <textarea
                            id="payment-reversal-reason"
                            rows={4}
                            required
                            value={reversalReason}
                            onChange={(event) =>
                                setReversalReason(event.target.value)
                            }
                            placeholder="Explain why this payment needs to be reversed..."
                            disabled={processingAction}
                            className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-rose-500 disabled:bg-slate-50"
                            />
                        </div>
                        </>
                    )}
                    </div>
                    <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-6 py-5">
                    <button
                        type="button"
                        onClick={() => {
                        setConfirmationAction(null);
                        setReversalReason("");
                        }}
                        disabled={processingAction}
                        className="h-10 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        type="submit"
                        disabled={
                        processingAction ||
                        (confirmationAction === "post" &&
                            !isFullyAllocated) ||
                        (confirmationAction === "reverse" &&
                            !reversalReason.trim())
                        }
                        className={`inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                        confirmationAction === "post"
                            ? "bg-emerald-600 hover:bg-emerald-700"
                            : "bg-rose-600 hover:bg-rose-700"
                        }`}
                    >
                        {processingAction && (
                        <LoaderCircle size={16} className="animate-spin" />
                        )}
                        {processingAction
                        ? "Processing..."
                        : confirmationAction === "post"
                            ? "Confirm posting"
                            : "Confirm reversal"}
                    </button>
                    </div>
                </form>
                </section>
            </div>
            )}
        {allocationToRemove && payment && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto bg-slate-950/40 p-4">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="allocation-removal-title"
              aria-describedby="allocation-removal-description"
              className="my-8 w-full max-w-md rounded-2xl bg-white shadow-xl"
            >
              <div className="border-b border-slate-100 px-6 py-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-50 text-rose-700">
                    <Trash2 size={19} />
                  </div>
                  <div>
                    <h2
                      id="allocation-removal-title"
                      className="font-bold text-slate-900"
                    >
                      Remove invoice allocation?
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      {currentReference}
                    </p>
                  </div>
                </div>
              </div>
              <div className="space-y-4 px-6 py-6">
                <div className="rounded-lg bg-slate-50 p-4">
                  <div className="flex justify-between gap-3 text-sm">
                    <span className="text-slate-500">Invoice</span>
                    <span className="font-semibold text-slate-900">
                      {allocationToRemove.invoiceNumber}
                    </span>
                  </div>
                  <div className="mt-3 flex justify-between gap-3 text-sm">
                    <span className="text-slate-500">Allocated amount</span>
                    <span className="font-semibold tabular-nums text-slate-900">
                      {formatAmount(
                        allocationToRemove.amount,
                        payment.currency,
                      )}
                    </span>
                  </div>
                </div>
                <p
                  id="allocation-removal-description"
                  className="text-sm leading-relaxed text-slate-600"
                >
                  This removes the allocation from this draft payment. It does
                  not delete the invoice or the vendor payment. You can allocate
                  the invoice again while the payment remains in draft.
                </p>
                {allocationRemovalError && (
                  <div
                    role="alert"
                    className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
                  >
                    <CircleAlert size={16} className="mt-0.5 shrink-0" />
                    <p>{allocationRemovalError}</p>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-6 py-5">
                <button
                  type="button"
                  onClick={() => {
                    setAllocationToRemove(null);
                    setAllocationRemovalError("");
                  }}
                  disabled={Boolean(removingInvoiceId)}
                  className="h-10 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmRemoveAllocation}
                  disabled={Boolean(removingInvoiceId)}
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-rose-600 px-4 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {removingInvoiceId ? (
                    <LoaderCircle size={16} className="animate-spin" />
                  ) : (
                    <Trash2 size={15} />
                  )}
                  {removingInvoiceId ? "Removing..." : "Remove allocation"}
                </button>
              </div>
            </section>
          </div>
        )}
      </main>
    </ProtectedRoute>
  );
}
export default function VendorPaymentDetailPage() {
  return (
    <ProtectedRoute>
      <VendorPaymentDetailWorkspace />
    </ProtectedRoute>
  );
}
