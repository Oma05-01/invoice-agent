"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import {
  Activity,
  BookOpen,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  FileText,
  Layers3,
  LoaderCircle,
  RefreshCw,
  Search,
  Wallet,
} from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { ProtectedRoute } from "@/components/protected-route";
import { JournalDetailPanel } from "@/components/accounting/journal-detail-panel";
import { AccountingReports } from "@/components/accounting/accounting-reports";

import {
  fetchAccountingAccounts,
  fetchJournalEntries,
  initializeChartOfAccounts,
} from "@/lib/accounting";

import type {
  AccountType,
  AccountingAccount,
  JournalEntry,
  JournalStatus,
} from "@/types/accounting";


type AccountingTab = "accounts" | "journals" | "reports";


const accountTypeLabels: Record<AccountType, string> = {
  asset: "Asset",
  liability: "Liability",
  equity: "Equity",
  income: "Income",
  expense: "Expense",
};

const accountTypeStyles: Record<AccountType, string> = {
  asset: "bg-blue-50 text-blue-700",
  liability: "bg-amber-50 text-amber-700",
  equity: "bg-violet-50 text-violet-700",
  income: "bg-emerald-50 text-emerald-700",
  expense: "bg-rose-50 text-rose-700",
};

const journalStatusLabels: Record<JournalStatus, string> = {
  draft: "Draft",
  posted: "Posted",
  reversed: "Reversed",
};

const journalStatusStyles: Record<JournalStatus, string> = {
  draft: "bg-amber-50 text-amber-700",
  posted: "bg-emerald-50 text-emerald-700",
  reversed: "bg-rose-50 text-rose-700",
};


function formatAmount(
  amount: number,
  currency: string,
): string {
  const safeCurrency = currency || "NGN";

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency: safeCurrency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${safeCurrency} ${amount.toLocaleString("en-NG", {
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
    .map((part) =>
      part.charAt(0).toUpperCase() + part.slice(1),
    )
    .join(" ");
}



function AccountTypeBadge({
  type,
}: {
  type: AccountType;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${accountTypeStyles[type]}`}
    >
      {accountTypeLabels[type]}
    </span>
  );
}


function JournalStatusBadge({
  status,
}: {
  status: JournalStatus;
}) {
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${journalStatusStyles[status]}`}
    >
      {journalStatusLabels[status]}
    </span>
  );
}


function SummaryCard({
  title,
  value,
  description,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  description: string;
  icon: typeof Wallet;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500">
            {title}
          </p>

          <p className="mt-3 text-2xl font-bold tracking-tight text-slate-900">
            {value}
          </p>

          <p className="mt-1 text-xs text-slate-400">
            {description}
          </p>
        </div>

        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
          <Icon size={19} />
        </div>
      </div>
    </div>
  );
}

function getJournalTotals(journal: JournalEntry) {
  const totals = journal.lines.reduce(
    (result, line) => ({
      debit: result.debit + Math.round(Number(line.debit) * 100),
      credit: result.credit + Math.round(Number(line.credit) * 100),
    }),
    { debit: 0, credit: 0 },
  );

  return {
    debit: totals.debit / 100,
    credit: totals.credit / 100,
  };
}


function AccountingWorkspace() {
  const { user } = useAuth();

  const organizations = user?.organizations ?? [];

  const [selectedOrganizationId, setSelectedOrganizationId] =
    useState("");

  const organizationId =
    selectedOrganizationId || organizations[0]?.id || "";

  const activeOrganization = organizations.find(
    (organization) => organization.id === organizationId,
  );

  const canInitializeAccounts = [
    "owner",
    "finance_admin",
  ].includes(activeOrganization?.role ?? "");

  const canEditDraft = [
    "owner",
    "finance_admin",
    "finance_operator",
    ].includes(activeOrganization?.role ?? "");

 const canPostOrReverse = [
    "owner",
    "finance_admin",
    ].includes(activeOrganization?.role ?? "");

  const [activeTab, setActiveTab] =
    useState<AccountingTab>("journals");

  const [accounts, setAccounts] = useState<AccountingAccount[]>([]);
  const [journals, setJournals] = useState<JournalEntry[]>([]);

  const [journalStatusFilter, setJournalStatusFilter] =
    useState<JournalStatus | "">("");

  const [searchInput, setSearchInput] = useState("");

  const [expandedJournalId, setExpandedJournalId] =
    useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const [initializing, setInitializing] = useState(false);

  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");


  // Load accounting data for the selected organization.
  useEffect(() => {
    if (!organizationId) return;

    const controller = new AbortController();

    async function loadAccountingData() {
      setLoading(true);
      setError("");
      setSuccessMessage("");

      try {
        const [accountData, journalData] = await Promise.all([
          fetchAccountingAccounts(
            organizationId,
            controller.signal,
          ),

          fetchJournalEntries(
            organizationId,
            "",
            controller.signal,
          ),
        ]);

        if (controller.signal.aborted) return;

        setAccounts(accountData.accounts);
        setJournals(journalData.journals);

        setExpandedJournalId(null);
      } catch (err) {
        if (controller.signal.aborted) return;

        setError(
          err instanceof Error
            ? err.message
            : "Unable to retrieve accounting information.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadAccountingData();

    return () => controller.abort();
  }, [organizationId, refreshKey]);


  // Initialize the starter chart of accounts.
  async function handleInitializeAccounts() {
    setInitializing(true);
    setError("");
    setSuccessMessage("");

    try {
      const result = await initializeChartOfAccounts(
        organizationId,
      );

      setAccounts(result.accounts);

      setSuccessMessage(
        "The chart of accounts has been initialized successfully.",
      );

      setRefreshKey((current) => current + 1);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to initialize the chart of accounts.",
      );
    } finally {
      setInitializing(false);
    }
  }


  function handleRefresh() {
    setRefreshKey((current) => current + 1);
  }


  function changeOrganization(value: string) {
    setSelectedOrganizationId(value);
    setJournalStatusFilter("");
    setSearchInput("");
    setExpandedJournalId(null);
    setError("");
    setSuccessMessage("");
  }


  const filteredJournals = useMemo(() => {
    const query = searchInput.trim().toLowerCase();

    return journals.filter((journal) => {
      const matchesStatus =
        !journalStatusFilter ||
        journal.status === journalStatusFilter;

      const matchesSearch =
        !query ||
        journal.reference.toLowerCase().includes(query) ||
        journal.description.toLowerCase().includes(query) ||
        journal.id.toLowerCase().includes(query);

      return matchesStatus && matchesSearch;
    });
  }, [journals, journalStatusFilter, searchInput]);


  const draftCount = journals.filter(
    (journal) => journal.status === "draft",
  ).length;

  const postedCount = journals.filter(
    (journal) => journal.status === "posted",
  ).length;

  const reversedCount = journals.filter(
    (journal) => journal.status === "reversed",
  ).length;


  return (
    <ProtectedRoute>
      <main className="min-h-screen bg-[#f5f7fb] text-slate-900">

        {/* Page header */}
        <header className="border-b border-slate-200 bg-white px-5 py-5 sm:px-8">
          <div className="mx-auto flex w-full max-w-[1800px] flex-col justify-between gap-4 sm:flex-row sm:items-center">

            <div>
              <p className="text-xs text-slate-400">
                Finance operations / Accounting
              </p>

              <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900">
                Accounting workspace
              </h1>

              <p className="mt-1 text-sm text-slate-500">
                Manage your chart of accounts and financial journals.
              </p>
            </div>

            <div className="min-w-0">
              <label
                htmlFor="accounting-organization"
                className="mb-1.5 block text-xs font-semibold text-slate-500"
              >
                Organization
              </label>

              <select
                id="accounting-organization"
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


        <div className="mx-auto w-full max-w-[1800px] p-4 sm:p-6 xl:p-8">

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

              {/* Organization information */}
              <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-5 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                    <Building2 size={19} />
                  </div>

                  <div>
                    <p className="text-sm font-semibold text-slate-800">
                      {activeOrganization?.name}
                    </p>

                    <p className="mt-0.5 text-xs text-slate-400">
                      Your role: {formatRole(activeOrganization?.role ?? "")}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw
                    size={14}
                    className={loading ? "animate-spin" : ""}
                  />
                  Refresh
                </button>
              </div>


              {/* Error and success messages */}
              {error && (
                <div
                  role="alert"
                  className="mb-5 flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
                >
                  <CircleAlert size={17} className="mt-0.5 shrink-0" />
                  <span>{error}</span>
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


              {/* Summary cards */}
              <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">

                <SummaryCard
                  title="Chart of accounts"
                  value={loading ? "—" : accounts.length}
                  description="Registered organization accounts"
                  icon={BookOpen}
                />

                <SummaryCard
                  title="Total journals"
                  value={loading ? "—" : journals.length}
                  description="Accounting entries"
                  icon={FileText}
                />

                <SummaryCard
                  title="Draft journals"
                  value={loading ? "—" : draftCount}
                  description="Awaiting finance review"
                  icon={Activity}
                />

                <SummaryCard
                  title="Posted journals"
                  value={loading ? "—" : postedCount}
                  description={`${reversedCount} reversed entries`}
                  icon={Wallet}
                />

              </section>


              {/* Main accounting workspace */}
              <section className="w-full min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">

                {/* Tabs */}
                <div className="flex gap-6 border-b border-slate-100 px-5">

                  <button
                    type="button"
                    onClick={() => setActiveTab("journals")}
                    className={`border-b-2 py-4 text-sm font-semibold transition ${
                      activeTab === "journals"
                        ? "border-blue-700 text-blue-700"
                        : "border-transparent text-slate-400 hover:text-slate-700"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <FileText size={16} />
                      Journal entries
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("accounts")}
                    className={`border-b-2 py-4 text-sm font-semibold transition ${
                      activeTab === "accounts"
                        ? "border-blue-700 text-blue-700"
                        : "border-transparent text-slate-400 hover:text-slate-700"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <Layers3 size={16} />
                      Chart of accounts
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("reports")}
                    className={`border-b-2 py-4 text-sm font-semibold transition ${
                        activeTab === "reports"
                        ? "border-blue-700 text-blue-700"
                        : "border-transparent text-slate-400 hover:text-slate-700"
                    }`}
                    >
                    <span className="flex items-center gap-2">
                        <Activity size={16} />
                        Reports
                    </span>
                </button>

                </div>


                {/* Chart of accounts */}
                {activeTab === "accounts" && (
                  <div>

                    <div className="flex flex-col justify-between gap-4 border-b border-slate-100 p-5 sm:flex-row sm:items-center">

                      <div>
                        <h2 className="text-sm font-bold text-slate-900">
                          Chart of accounts
                        </h2>

                        <p className="mt-1 text-xs text-slate-400">
                          Financial accounts configured for this organization.
                        </p>
                      </div>

                      {canInitializeAccounts && (
                        <button
                          type="button"
                          onClick={handleInitializeAccounts}
                          disabled={initializing || loading}
                          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {initializing ? (
                            <LoaderCircle
                              size={15}
                              className="animate-spin"
                            />
                          ) : (
                            <Layers3 size={15} />
                          )}

                          {initializing
                            ? "Initializing..."
                            : "Initialize starter accounts"}
                        </button>
                      )}

                    </div>


                    <div className="overflow-x-auto">

                      <table className="w-full min-w-[750px] text-left">

                        <thead>
                          <tr className="bg-slate-50">
                            <th className="px-5 py-3 text-xs font-semibold text-slate-500">
                              Code
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Account name
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Account type
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Control account
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Status
                            </th>
                          </tr>
                        </thead>


                        <tbody className="divide-y divide-slate-100">

                          {loading ? (
                            <tr>
                              <td colSpan={5} className="py-16 text-center">
                                <LoaderCircle
                                  size={25}
                                  className="mx-auto animate-spin text-blue-600"
                                />

                                <p className="mt-3 text-sm text-slate-500">
                                  Loading accounts...
                                </p>
                              </td>
                            </tr>
                          ) : accounts.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="px-5 py-16 text-center">
                                <BookOpen
                                  size={30}
                                  className="mx-auto text-slate-300"
                                />

                                <p className="mt-3 text-sm font-semibold text-slate-700">
                                  No accounts configured
                                </p>

                                <p className="mt-1 text-xs text-slate-400">
                                  Initialize the starter chart to begin recording
                                  accounting entries.
                                </p>

                                {!canInitializeAccounts && (
                                  <p className="mt-3 text-xs text-slate-500">
                                    Ask an organization owner or finance
                                    administrator to initialize the chart.
                                  </p>
                                )}
                              </td>
                            </tr>
                          ) : (
                            accounts.map((account) => (
                              <tr
                                key={account.id}
                                className="transition hover:bg-slate-50/70"
                              >
                                <td className="px-5 py-4">
                                  <span className="font-mono text-sm font-semibold text-slate-800">
                                    {account.code}
                                  </span>
                                </td>

                                <td className="px-4 py-4">
                                  <p className="text-sm font-semibold text-slate-800">
                                    {account.name}
                                  </p>

                                  {account.description && (
                                    <p className="mt-1 max-w-md text-xs text-slate-400">
                                      {account.description}
                                    </p>
                                  )}
                                </td>

                                <td className="px-4 py-4">
                                  <AccountTypeBadge
                                    type={account.account_type}
                                  />
                                </td>

                                <td className="px-4 py-4 text-xs text-slate-500">
                                  {account.is_control_account ? "Yes" : "No"}
                                </td>

                                <td className="px-4 py-4">
                                  <span
                                    className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                                      account.is_active
                                        ? "bg-emerald-50 text-emerald-700"
                                        : "bg-slate-100 text-slate-500"
                                    }`}
                                  >
                                    {account.is_active ? "Active" : "Inactive"}
                                  </span>
                                </td>
                              </tr>
                            ))
                          )}

                        </tbody>

                      </table>

                    </div>

                    <div className="border-t border-slate-100 px-5 py-4">
                      <p className="text-xs text-slate-400">
                        {accounts.length} accounts configured for this organization.
                      </p>
                    </div>

                  </div>
                )}


                {/* Journal entries */}
                {activeTab === "journals" && (
                  <div>

                    <div className="flex flex-col justify-between gap-4 border-b border-slate-100 p-5 lg:flex-row lg:items-center">

                      <div>
                        <h2 className="text-sm font-bold text-slate-900">
                          Journal entries
                        </h2>

                        <p className="mt-1 text-xs text-slate-400">
                          Review the accounting entries generated from approved invoices.
                        </p>
                      </div>


                      <div className="flex flex-col gap-2 sm:flex-row">

                        <div className="relative">
                          <Search
                            size={15}
                            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                          />

                          <input
                            type="search"
                            value={searchInput}
                            onChange={(event) =>
                              setSearchInput(event.target.value)
                            }
                            placeholder="Search journals..."
                            className="h-10 w-full rounded-lg border border-slate-200 pl-9 pr-3 text-xs outline-none focus:border-blue-500 sm:w-52"
                          />
                        </div>


                        <div className="relative">
                          <select
                            value={journalStatusFilter}
                            onChange={(event) =>
                              setJournalStatusFilter(
                                event.target.value as JournalStatus | "",
                              )
                            }
                            className="h-10 w-full appearance-none rounded-lg border border-slate-200 bg-white py-2 pl-3 pr-9 text-xs text-slate-700 outline-none focus:border-blue-500 sm:w-40"
                          >
                            <option value="">All statuses</option>
                            <option value="draft">Draft</option>
                            <option value="posted">Posted</option>
                            <option value="reversed">Reversed</option>
                          </select>

                          <ChevronDown
                            size={14}
                            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
                          />
                        </div>

                      </div>

                    </div>


                    <div className="overflow-x-auto">

                      <table className="w-full min-w-[950px] text-left">

                        <thead>
                          <tr className="bg-slate-50">
                            <th className="px-5 py-3 text-xs font-semibold text-slate-500">
                              Reference
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Entry date
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Currency
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Debit
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Credit
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Status
                            </th>

                            <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                              Details
                            </th>
                          </tr>
                        </thead>


                        <tbody className="divide-y divide-slate-100">

                          {loading ? (
                            <tr>
                              <td colSpan={7} className="py-16 text-center">
                                <LoaderCircle
                                  size={25}
                                  className="mx-auto animate-spin text-blue-600"
                                />

                                <p className="mt-3 text-sm text-slate-500">
                                  Loading journal entries...
                                </p>
                              </td>
                            </tr>
                          ) : filteredJournals.length === 0 ? (
                            <tr>
                              <td colSpan={7} className="px-5 py-16 text-center">
                                <FileText
                                  size={30}
                                  className="mx-auto text-slate-300"
                                />

                                <p className="mt-3 text-sm font-semibold text-slate-700">
                                  No matching journal entries
                                </p>

                                <p className="mt-1 text-xs text-slate-400">
                                  Approved invoices generate draft journals
                                  automatically.
                                </p>
                              </td>
                            </tr>
                          ) : (
                            filteredJournals.map((journal) => {
                              const totals = getJournalTotals(journal);
                            
                              const expanded =
                                expandedJournalId === journal.id;

                                const reversalJournal = journals.find(
                                (candidate) => candidate.reversal_of_id === journal.id,
                                );

                              return (
                                <Fragment key={journal.id}>

                                  <tr
                                    className={`transition ${
                                      expanded
                                        ? "bg-blue-50/40"
                                        : "hover:bg-slate-50/70"
                                    }`}
                                  >

                                    <td className="px-5 py-4">
                                      <p className="text-sm font-semibold text-slate-800">
                                        {journal.reference || journal.id.slice(0, 8)}
                                      </p>

                                      <p className="mt-1 text-xs text-slate-400">
                                        {journal.source_invoice_id
                                          ? "Invoice journal"
                                          : journal.reversal_of_id
                                            ? "Reversal journal"
                                            : "General journal"}
                                      </p>
                                    </td>

                                    <td className="px-4 py-4 text-sm text-slate-500">
                                      {formatDate(journal.entry_date)}
                                    </td>

                                    <td className="px-4 py-4 text-sm text-slate-600">
                                      {journal.currency}
                                    </td>

                                    <td className="whitespace-nowrap px-4 py-4 text-sm font-medium text-slate-800">
                                      {formatAmount(
                                        totals.debit,
                                        journal.currency,
                                      )}
                                    </td>

                                    <td className="whitespace-nowrap px-4 py-4 text-sm font-medium text-slate-800">
                                      {formatAmount(
                                        totals.credit,
                                        journal.currency,
                                      )}
                                    </td>

                                    <td className="px-4 py-4">
                                      <JournalStatusBadge
                                        status={journal.status}
                                      />
                                    </td>

                                    <td className="px-4 py-4">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setExpandedJournalId(
                                            expanded ? null : journal.id,
                                          )
                                        }
                                        aria-expanded={expanded}
                                        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                                      >
                                        {expanded ? "Hide" : "View"}

                                        {expanded ? (
                                          <ChevronDown size={14} />
                                        ) : (
                                          <ChevronRight size={14} />
                                        )}
                                      </button>
                                    </td>

                                  </tr>


                                  {expanded && (
                                    <tr>
                                        <td
                                        colSpan={7}
                                        className="bg-slate-50/80 px-5 py-5"
                                        >
                                        <JournalDetailPanel
                                            organizationId={organizationId}
                                            journal={journal}
                                            accounts={accounts}
                                            canEditDraft={canEditDraft}
                                            canPostOrReverse={canPostOrReverse}
                                            reversalJournal={reversalJournal}
                                            onChanged={handleRefresh}
                                        />
                                        </td>
                                    </tr>
                                    )}

                                </Fragment>
                              );
                            })
                          )}

                        </tbody>

                      </table>

                    </div>


                    <div className="flex flex-col justify-between gap-2 border-t border-slate-100 px-5 py-4 sm:flex-row sm:items-center">
                      <p className="text-xs text-slate-400">
                        Showing {filteredJournals.length} of {journals.length} journal entries.
                      </p>

                      <p className="text-xs text-slate-400">
                        Journal entries are restricted to the selected organization.
                      </p>
                    </div>

                  </div>
                )}

                {/* Reports */}
                {activeTab === "reports" && (
                  <AccountingReports
                    organizationId={organizationId}
                    accounts={accounts}
                  />
                )}

              </section>


              {/* Accounting information */}
              <div className="mt-6 rounded-xl border border-blue-100 bg-blue-50/60 p-5">

                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-blue-700">
                    <Activity size={18} />
                  </div>

                  <div>
                    <h3 className="text-sm font-bold text-slate-800">
                      Controlled financial record keeping
                    </h3>

                    <p className="mt-1 max-w-4xl text-xs leading-6 text-slate-600">
                      Approved invoices generate draft accounting journals.
                      Finance personnel review account classifications and
                      journal balances before authorized administrators post
                      them. Posted entries are preserved, and corrections
                      to posted journals are recorded through reversals.
                    </p>
                  </div>
                </div>

              </div>

            </>
          )}

        </div>

      </main>
    </ProtectedRoute>
  );
}


export default function AccountingPage() {
  return (
    <ProtectedRoute>
      <AccountingWorkspace />
    </ProtectedRoute>
  );
}
