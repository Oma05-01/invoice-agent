"use client";

import { useState, type FormEvent } from "react";

import {
  BookOpen,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  FileBarChart,
  LoaderCircle,
  Scale,
  Search,
  TrendingUp,
  Landmark,
} from "lucide-react";

import {
  fetchAccountLedger,
  fetchTrialBalance,
  fetchIncomeStatement,
  fetchBalanceSheet,
} from "@/lib/accounting";

import type {
  AccountLedgerResponse,
  AccountingAccount,
  BalanceSide,
  JournalStatus,
  TrialBalanceResponse,
  IncomeStatementResponse,
  BalanceSheetResponse,
} from "@/types/accounting";


type Props = {
  organizationId: string;
  accounts: AccountingAccount[];
};

type ReportTab = "ledger" | "trial-balance" | "income-statement" | "balance-sheet";


const journalStatusStyles: Record<JournalStatus, string> = {
  draft: "bg-amber-50 text-amber-700",
  posted: "bg-emerald-50 text-emerald-700",
  reversed: "bg-rose-50 text-rose-700",
};


function getLocalDateValue() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}


function formatReportAmount(value: string, currency: string) {
  const amount = Number(value);

  if (!Number.isFinite(amount)) return "—";

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}


function formatReportDate(value: string | null) {
  if (!value) return "—";

  const date = new Date(`${value.slice(0, 10)}T00:00:00`);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}


function formatBalanceSide(side: BalanceSide) {
  if (side === "debit") return "Dr";
  if (side === "credit") return "Cr";

  return "—";
}


function ReportEmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="px-5 py-16 text-center">
      <FileBarChart size={30} className="mx-auto text-slate-300" />
      <p className="mt-3 text-sm font-semibold text-slate-700">
        {title}
      </p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-slate-400">
        {description}
      </p>
    </div>
  );
}


function ReportBasisNotice({ value }: { value: string }) {
  return (
    <div className="mt-5 rounded-lg border border-blue-100 bg-blue-50/60 p-4">
      <p className="text-xs leading-5 text-blue-800">{value}</p>
    </div>
  );
}


function LedgerReport({
  organizationId,
  accounts,
}: {
  organizationId: string;
  accounts: AccountingAccount[];
}) {
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const accountId = accounts.some((account) => account.id === selectedAccountId)
    ? selectedAccountId
    : accounts[0]?.id ?? "";

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [report, setReport] = useState<AccountLedgerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!accountId) {
      setError("Select an account before generating the ledger.");
      return;
    }

    if (startDate && endDate && startDate > endDate) {
      setError("The end date cannot be earlier than the start date.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);

    try {
      const result = await fetchAccountLedger(organizationId, accountId, {
        startDate: startDate || undefined,
        endDate: endDate || undefined,
      });
      setReport(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to generate the general ledger.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full min-w-0">
      <div className="border-b border-slate-100 p-5">
        <h2 className="text-sm font-bold text-slate-900">General Ledger</h2>
        <p className="mt-1 text-xs text-slate-400">
          Inspect the transaction history and running balance of an account.
        </p>
      </div>

      <form
        onSubmit={handleGenerateReport}
        className="grid grid-cols-1 gap-4 border-b border-slate-100 bg-slate-50/60 p-5 md:grid-cols-2 xl:grid-cols-4"
      >
        <div className="min-w-0 md:col-span-2 xl:col-span-2">
          <label
            htmlFor="ledger-account"
            className="mb-1.5 block text-xs font-semibold text-slate-600"
          >
            Ledger account
          </label>
          <select
            id="ledger-account"
            value={accountId}
            onChange={(event) => {
              setSelectedAccountId(event.target.value);
              setReport(null);
              setError("");
            }}
            className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
            required
          >
            <option value="">Select an account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.code} — {account.name}
              </option>
            ))}
          </select>
        </div>

        <div className="min-w-0">
          <label
            htmlFor="ledger-start-date"
            className="mb-1.5 block text-xs font-semibold text-slate-600"
          >
            Start date
          </label>
          <input
            id="ledger-start-date"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            max={endDate || undefined}
            className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
          />
        </div>

        <div className="min-w-0">
          <label
            htmlFor="ledger-end-date"
            className="mb-1.5 block text-xs font-semibold text-slate-600"
          >
            End date
          </label>
          <input
            id="ledger-end-date"
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
            min={startDate || undefined}
            className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
          />
        </div>

        <div className="md:col-span-2 xl:col-span-4">
          <button
            type="submit"
            disabled={loading || accounts.length === 0}
            className="inline-flex h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-blue-700 px-5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:min-w-[190px]"
          >
            {loading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <Search size={16} />
            )}
            {loading ? "Generating report..." : "Generate ledger"}
          </button>
        </div>
      </form>

      {error && (
        <div
          role="alert"
          className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
        >
          {error}
        </div>
      )}

      {!report && !loading && !error && (
        <ReportEmptyState
          title="No ledger report generated"
          description="Select an account and optionally specify a date range, then generate the report."
        />
      )}

      {report && (
        <div className="w-full min-w-0 p-4 sm:p-5">
          <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <h3 className="break-words text-lg font-bold text-slate-900">
                {report.account.code} — {report.account.name}
              </h3>
              <p className="mt-1 text-xs text-slate-500">
                {report.period.start_date
                  ? `From ${formatReportDate(report.period.start_date)}`
                  : "All available history"}
                {" · "}
                {report.period.end_date
                  ? `To ${formatReportDate(report.period.end_date)}`
                  : "Up to present"}
              </p>
            </div>
            <span className="self-start rounded-full bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">
              {report.count} transaction{report.count === 1 ? "" : "s"}
            </span>
          </div>

          {/* Opening balances */}
          <section className="mb-5">
            <h4 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500">
              Opening balances
            </h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {report.opening_balances.map((balance) => (
                <div
                  key={balance.currency}
                  className="rounded-lg border border-slate-200 bg-slate-50 p-4"
                >
                  <p className="text-xs text-slate-500">{balance.currency}</p>
                  <p className="mt-2 text-lg font-bold text-slate-900">
                    {formatReportAmount(balance.amount, balance.currency)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatBalanceSide(balance.side)} balance
                  </p>
                </div>
              ))}
            </div>
          </section>

          {/* Transactions */}
          <section className="w-full min-w-0 rounded-xl border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-4">
              <h4 className="text-sm font-bold text-slate-800">
                Account transactions
              </h4>
              <p className="mt-1 text-xs text-slate-400">
                Individual postings and their running balances.
              </p>
            </div>

            {/* Desktop and laptop table: all seven columns fit the available width. */}
            <div className="hidden w-full min-w-0 lg:block">
              <table className="w-full min-w-0 table-fixed text-left">
                <thead>
                  <tr className="bg-slate-50">
                    <th className="w-[10%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Date
                    </th>
                    <th className="w-[14%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Reference
                    </th>
                    <th className="w-[22%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Description
                    </th>
                    <th className="w-[10%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Status
                    </th>
                    <th className="w-[13%] px-2 py-3 text-right text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Debit
                    </th>
                    <th className="w-[13%] px-2 py-3 text-right text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Credit
                    </th>
                    <th className="w-[18%] px-2 py-3 text-right text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                      Running balance
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {report.transactions.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-4 py-12 text-center text-sm text-slate-400"
                      >
                        No transactions in this period.
                      </td>
                    </tr>
                  ) : (
                    report.transactions.map((transaction) => (
                      <tr key={transaction.line_id} className="hover:bg-slate-50/70">
                        <td className="break-words px-2 py-3 text-[11px] text-slate-500 xl:px-3 xl:text-xs">
                          {formatReportDate(transaction.entry_date)}
                        </td>
                        <td className="break-words px-2 py-3 xl:px-3">
                          <p className="break-words text-[11px] font-semibold leading-4 text-slate-800 xl:text-xs">
                            {transaction.reference || "—"}
                          </p>
                          <p className="mt-1 font-mono text-[10px] text-slate-400">
                            Line {transaction.line_number}
                          </p>
                        </td>
                        <td className="whitespace-normal break-words px-2 py-3 xl:px-3">
                          <p className="text-[11px] leading-4 text-slate-700 xl:text-xs">
                            {transaction.description || "—"}
                          </p>
                        </td>
                        <td className="px-2 py-3 xl:px-3">
                          <span
                            className={`inline-flex rounded-full px-1.5 py-1 text-[9px] font-semibold capitalize xl:px-2 xl:text-[10px] ${journalStatusStyles[transaction.journal_status]}`}
                          >
                            {transaction.journal_status}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-2 py-3 text-right text-[10px] font-medium text-slate-800 xl:px-3 xl:text-xs">
                          {Number(transaction.debit) > 0
                            ? formatReportAmount(
                                transaction.debit,
                                transaction.currency,
                              )
                            : "—"}
                        </td>
                        <td className="whitespace-nowrap px-2 py-3 text-right text-[10px] font-medium text-slate-800 xl:px-3 xl:text-xs">
                          {Number(transaction.credit) > 0
                            ? formatReportAmount(
                                transaction.credit,
                                transaction.currency,
                              )
                            : "—"}
                        </td>
                        <td className="whitespace-nowrap px-2 py-3 text-right xl:px-3">
                          <p className="text-[10px] font-bold text-slate-900 xl:text-xs">
                            {formatReportAmount(
                              transaction.running_balance.amount,
                              transaction.currency,
                            )}
                          </p>
                          <p className="mt-0.5 text-[10px] text-slate-400">
                            {formatBalanceSide(transaction.running_balance.side)}
                          </p>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Mobile and narrow-screen transaction cards. */}
            <div className="divide-y divide-slate-100 lg:hidden">
              {report.transactions.length === 0 ? (
                <div className="px-4 py-12 text-center text-sm text-slate-400">
                  No transactions in this period.
                </div>
              ) : (
                report.transactions.map((transaction) => (
                  <article
                    key={transaction.line_id}
                    className="space-y-3 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="break-words text-sm font-bold text-slate-800">
                          {transaction.reference || "Journal entry"}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {formatReportDate(transaction.entry_date)}
                        </p>
                        <p className="mt-1 font-mono text-[10px] text-slate-400">
                          Line {transaction.line_number}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold capitalize ${journalStatusStyles[transaction.journal_status]}`}
                      >
                        {transaction.journal_status}
                      </span>
                    </div>

                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                        Description
                      </p>
                      <p className="mt-1 break-words text-xs leading-5 text-slate-700">
                        {transaction.description || "—"}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="min-w-0">
                        <p className="text-[10px] text-slate-500">Debit</p>
                        <p className="mt-1 break-words text-sm font-semibold text-slate-800">
                          {Number(transaction.debit) > 0
                            ? formatReportAmount(
                                transaction.debit,
                                transaction.currency,
                              )
                            : "—"}
                        </p>
                      </div>
                      <div className="min-w-0">
                        <p className="text-[10px] text-slate-500">Credit</p>
                        <p className="mt-1 break-words text-sm font-semibold text-slate-800">
                          {Number(transaction.credit) > 0
                            ? formatReportAmount(
                                transaction.credit,
                                transaction.currency,
                              )
                            : "—"}
                        </p>
                      </div>
                    </div>

                    <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-3">
                      <p className="text-[10px] font-medium text-blue-700">
                        Running balance
                      </p>
                      <p className="mt-1 break-words text-base font-bold text-slate-900">
                        {formatReportAmount(
                          transaction.running_balance.amount,
                          transaction.currency,
                        )}
                      </p>
                      <p className="mt-1 text-[10px] text-slate-500">
                        {formatBalanceSide(transaction.running_balance.side)} balance
                      </p>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>

          {/* Period totals */}
          <section className="mt-5">
            <h4 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500">
              Period activity
            </h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {report.totals_by_currency.map((total) => (
                <div
                  key={total.currency}
                  className="rounded-lg border border-slate-200 bg-white p-4"
                >
                  <p className="text-xs font-semibold text-slate-500">
                    {total.currency} activity
                  </p>
                  <div className="mt-3 flex justify-between gap-2 text-xs">
                    <span className="text-slate-500">Debits</span>
                    <strong className="text-slate-800">
                      {formatReportAmount(total.debit, total.currency)}
                    </strong>
                  </div>
                  <div className="mt-2 flex justify-between gap-2 text-xs">
                    <span className="text-slate-500">Credits</span>
                    <strong className="text-slate-800">
                      {formatReportAmount(total.credit, total.currency)}
                    </strong>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Closing balances */}
          <section className="mt-5">
            <h4 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500">
              Closing balances
            </h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {report.closing_balances.map((balance) => (
                <div
                  key={balance.currency}
                  className="rounded-lg border border-blue-200 bg-blue-50/50 p-4"
                >
                  <p className="text-xs font-semibold text-blue-700">
                    {balance.currency} closing balance
                  </p>
                  <p className="mt-2 text-xl font-bold text-slate-900">
                    {formatReportAmount(balance.amount, balance.currency)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatBalanceSide(balance.side)} balance
                  </p>
                </div>
              ))}
            </div>
          </section>

          <ReportBasisNotice value={report.report_basis} />
        </div>
      )}
    </div>
  );
}


function TrialBalanceReport({
  organizationId,
}: {
  organizationId: string;
}) {
  const [asOfDate, setAsOfDate] = useState(getLocalDateValue);
  const [report, setReport] = useState<TrialBalanceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!asOfDate) {
      setError("Select an as-of date.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);

    try {
      const result = await fetchTrialBalance(organizationId, asOfDate);
      setReport(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to generate the trial balance.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full min-w-0">
      <div className="border-b border-slate-100 p-5">
        <h2 className="text-sm font-bold text-slate-900">Trial Balance</h2>
        <p className="mt-1 text-xs text-slate-400">
          Review the debit and credit balances of all ledger accounts as of a selected date.
        </p>
      </div>

      <form
        onSubmit={handleGenerateReport}
        className="flex flex-col gap-4 border-b border-slate-100 bg-slate-50/60 p-5 sm:flex-row sm:items-end"
      >
        <div className="w-full min-w-0 sm:max-w-xs">
          <label
            htmlFor="trial-balance-date"
            className="mb-1.5 block text-xs font-semibold text-slate-600"
          >
            Report as of
          </label>
          <div className="relative">
            <CalendarDays
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              id="trial-balance-date"
              type="date"
              value={asOfDate}
              onChange={(event) => setAsOfDate(event.target.value)}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none focus:border-blue-500"
              required
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="inline-flex h-10 w-full shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-blue-700 px-5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:min-w-[220px]"
        >
          {loading ? (
            <LoaderCircle size={16} className="animate-spin" />
          ) : (
            <Search size={16} />
          )}
          {loading ? "Generating report..." : "Generate trial balance"}
        </button>
      </form>

      {error && (
        <div
          role="alert"
          className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
        >
          {error}
        </div>
      )}

      {!report && !loading && !error && (
        <ReportEmptyState
          title="No trial balance generated"
          description="Choose an as-of date to calculate the organization's account balances."
        />
      )}

      {report && (
        <div className="w-full min-w-0 space-y-6 p-4 sm:p-5">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Trial Balance</h3>
            <p className="mt-1 text-xs text-slate-500">
              Balances as of {formatReportDate(report.as_of_date)}
            </p>
          </div>

          {report.currencies.map((currencyReport) => (
            <section
              key={currencyReport.currency}
              className="w-full min-w-0 rounded-xl border border-slate-200 bg-white"
            >
              <div className="flex flex-col justify-between gap-3 border-b border-slate-100 bg-slate-50 p-4 sm:flex-row sm:items-center">
                <div>
                  <h4 className="text-sm font-bold text-slate-900">
                    {currencyReport.currency} trial balance
                  </h4>
                  <p className="mt-1 text-xs text-slate-400">
                    {currencyReport.accounts.length} ledger accounts
                  </p>
                </div>

                {currencyReport.is_balanced ? (
                  <span className="inline-flex items-center gap-1.5 self-start rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 sm:self-auto">
                    <CheckCircle2 size={14} />
                    Balanced
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 self-start rounded-full bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-700 sm:self-auto">
                    <CircleAlert size={14} />
                    Out of balance
                  </span>
                )}
              </div>

              {/* Desktop and laptop table: all five columns fit the available width. */}
              <div className="hidden w-full min-w-0 lg:block">
                <table className="w-full min-w-0 table-fixed text-left">
                  <thead>
                    <tr className="bg-white">
                      <th className="w-[12%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                        Account code
                      </th>
                      <th className="w-[29%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                        Account name
                      </th>
                      <th className="w-[16%] px-2 py-3 text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                        Account type
                      </th>
                      <th className="w-[21.5%] px-2 py-3 text-right text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                        Debit balance
                      </th>
                      <th className="w-[21.5%] px-2 py-3 text-right text-[11px] font-semibold text-slate-500 xl:px-3 xl:text-xs">
                        Credit balance
                      </th>
                    </tr>
                  </thead>

                  <tbody className="divide-y divide-slate-100">
                    {currencyReport.accounts.map((account) => (
                      <tr key={account.id} className="hover:bg-slate-50/70">
                        <td className="break-words px-2 py-3 font-mono text-[11px] font-semibold text-slate-700 xl:px-3 xl:text-xs">
                          {account.code}
                        </td>
                        <td className="whitespace-normal break-words px-2 py-3 xl:px-3">
                          <p className="text-[11px] font-semibold leading-4 text-slate-800 xl:text-xs">
                            {account.name}
                          </p>
                          {!account.is_active && (
                            <span className="mt-1 inline-block text-[10px] text-slate-400">
                              Inactive account
                            </span>
                          )}
                        </td>
                        <td className="whitespace-normal break-words px-2 py-3 text-[11px] capitalize text-slate-500 xl:px-3 xl:text-xs">
                          {account.account_type}
                        </td>
                        <td className="whitespace-nowrap px-2 py-3 text-right text-[10px] font-medium text-slate-800 xl:px-3 xl:text-xs">
                          {Number(account.debit_balance) > 0
                            ? formatReportAmount(
                                account.debit_balance,
                                currencyReport.currency,
                              )
                            : "—"}
                        </td>
                        <td className="whitespace-nowrap px-2 py-3 text-right text-[10px] font-medium text-slate-800 xl:px-3 xl:text-xs">
                          {Number(account.credit_balance) > 0
                            ? formatReportAmount(
                                account.credit_balance,
                                currencyReport.currency,
                              )
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>

                  <tfoot>
                    <tr className="border-t-2 border-slate-200 bg-slate-50">
                      <td
                        colSpan={3}
                        className="px-2 py-4 text-[11px] font-bold text-slate-800 xl:px-3 xl:text-xs"
                      >
                        Total balances
                      </td>
                      <td className="whitespace-nowrap px-2 py-4 text-right text-[10px] font-bold text-slate-900 xl:px-3 xl:text-xs">
                        {formatReportAmount(
                          currencyReport.totals.debit_balance,
                          currencyReport.currency,
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-4 text-right text-[10px] font-bold text-slate-900 xl:px-3 xl:text-xs">
                        {formatReportAmount(
                          currencyReport.totals.credit_balance,
                          currencyReport.currency,
                        )}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              {/* Mobile and narrow-screen account cards. */}
              <div className="divide-y divide-slate-100 lg:hidden">
                {currencyReport.accounts.map((account) => (
                  <article key={account.id} className="space-y-3 p-4">
                    <div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-mono text-sm font-bold text-slate-700">
                          {account.code}
                        </span>
                        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-semibold capitalize text-blue-700">
                          {account.account_type}
                        </span>
                      </div>
                      <h4 className="mt-2 break-words text-sm font-semibold leading-5 text-slate-900">
                        {account.name}
                      </h4>
                      {!account.is_active && (
                        <p className="mt-1 text-[10px] text-slate-400">
                          Inactive account
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="min-w-0 rounded-lg bg-slate-50 p-3">
                        <p className="text-[10px] font-medium text-slate-500">
                          Debit balance
                        </p>
                        <p className="mt-2 break-words text-sm font-bold text-slate-900">
                          {Number(account.debit_balance) > 0
                            ? formatReportAmount(
                                account.debit_balance,
                                currencyReport.currency,
                              )
                            : "—"}
                        </p>
                      </div>
                      <div className="min-w-0 rounded-lg bg-slate-50 p-3">
                        <p className="text-[10px] font-medium text-slate-500">
                          Credit balance
                        </p>
                        <p className="mt-2 break-words text-sm font-bold text-slate-900">
                          {Number(account.credit_balance) > 0
                            ? formatReportAmount(
                                account.credit_balance,
                                currencyReport.currency,
                              )
                            : "—"}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}

                {/* Mobile totals */}
                <div className="space-y-3 bg-slate-50 p-4">
                  <h4 className="text-sm font-bold text-slate-800">
                    Total balances
                  </h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="min-w-0">
                      <p className="text-[10px] text-slate-500">Total debits</p>
                      <p className="mt-1 break-words text-sm font-bold text-slate-900">
                        {formatReportAmount(
                          currencyReport.totals.debit_balance,
                          currencyReport.currency,
                        )}
                      </p>
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] text-slate-500">Total credits</p>
                      <p className="mt-1 break-words text-sm font-bold text-slate-900">
                        {formatReportAmount(
                          currencyReport.totals.credit_balance,
                          currencyReport.currency,
                        )}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          ))}

          <ReportBasisNotice value={report.report_basis} />

          <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-600">
            <Scale size={16} className="mt-0.5 shrink-0 text-slate-500" />
            <p>
              A balanced trial balance means total debit balances equal
              total credit balances within each currency. It does not,
              by itself, establish that every account has been classified
              correctly.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


type StatementRow = {
  id: string;
  code: string;
  name: string;
  amount: string;
};

function StatementAccountSection({
  title,
  rows,
  currency,
  totalLabel,
  totalAmount,
  emptyMessage,
}: {
  title: string;
  rows: StatementRow[];
  currency: string;
  totalLabel: string;
  totalAmount: string;
  emptyMessage: string;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <h4 className="text-sm font-bold text-slate-800">{title}</h4>
        <span className="text-xs text-slate-400">
          {rows.length} account{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-6 text-xs text-slate-400">{emptyMessage}</p>
      ) : (
        <>
          <div className="hidden sm:block">
            <table className="w-full table-fixed text-left">
              <thead>
                <tr className="bg-white">
                  <th className="w-[18%] px-4 py-3 text-xs font-semibold text-slate-500">Code</th>
                  <th className="w-[57%] px-4 py-3 text-xs font-semibold text-slate-500">Account</th>
                  <th className="w-[25%] px-4 py-3 text-right text-xs font-semibold text-slate-500">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((row) => (
                  <tr key={row.id} className="hover:bg-slate-50/70">
                    <td className="break-words px-4 py-3 font-mono text-xs font-semibold text-slate-600">{row.code}</td>
                    <td className="whitespace-normal break-words px-4 py-3 text-xs font-medium text-slate-800">{row.name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-xs font-semibold text-slate-800">
                      {formatReportAmount(row.amount, currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-200 bg-slate-50">
                  <td colSpan={2} className="px-4 py-3 text-xs font-bold text-slate-800">{totalLabel}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-xs font-bold text-slate-900">
                    {formatReportAmount(totalAmount, currency)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="divide-y divide-slate-100 sm:hidden">
            {rows.map((row) => (
              <article key={row.id} className="flex items-start justify-between gap-3 p-4">
                <div className="min-w-0">
                  <p className="font-mono text-xs font-semibold text-slate-500">{row.code}</p>
                  <p className="mt-1 break-words text-sm font-semibold leading-5 text-slate-800">{row.name}</p>
                </div>
                <p className="shrink-0 text-right text-xs font-bold text-slate-900">
                  {formatReportAmount(row.amount, currency)}
                </p>
              </article>
            ))}
            <div className="flex items-center justify-between gap-3 bg-slate-50 p-4">
              <span className="text-xs font-bold text-slate-800">{totalLabel}</span>
              <span className="text-right text-xs font-bold text-slate-900">
                {formatReportAmount(totalAmount, currency)}
              </span>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function StatementMetric({
  label,
  amount,
  currency,
  emphasis = false,
}: {
  label: string;
  amount: string;
  currency: string;
  emphasis?: boolean;
}) {
  return (
    <div className={`min-w-0 rounded-xl border p-4 ${emphasis ? "border-blue-200 bg-blue-50/60" : "border-slate-200 bg-white"}`}>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-2 break-words text-lg font-bold text-slate-900 sm:text-xl">
        {formatReportAmount(amount, currency)}
      </p>
    </div>
  );
}

function IncomeStatementReport({
  organizationId,
}: {
  organizationId: string;
}) {
  const yearStart = `${new Date().getFullYear()}-01-01`;
  const [startDate, setStartDate] = useState(yearStart);
  const [endDate, setEndDate] = useState(getLocalDateValue);
  const [report, setReport] = useState<IncomeStatementResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!startDate || !endDate) {
      setError("Select both a start date and an end date.");
      return;
    }
    if (startDate > endDate) {
      setError("The end date cannot be earlier than the start date.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);
    try {
      const result = await fetchIncomeStatement(organizationId, startDate, endDate);
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate the income statement.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full min-w-0">
      <div className="border-b border-slate-100 p-5">
        <h2 className="text-sm font-bold text-slate-900">Income Statement</h2>
        <p className="mt-1 text-xs text-slate-400">
          Review revenue, expenses and net income over a selected period.
        </p>
      </div>

      <form onSubmit={handleGenerateReport} className="grid grid-cols-1 gap-4 border-b border-slate-100 bg-slate-50/60 p-5 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-0">
          <label htmlFor="income-start-date" className="mb-1.5 block text-xs font-semibold text-slate-600">Start date</label>
          <input id="income-start-date" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} max={endDate || undefined} required className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500" />
        </div>
        <div className="min-w-0">
          <label htmlFor="income-end-date" className="mb-1.5 block text-xs font-semibold text-slate-600">End date</label>
          <input id="income-end-date" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} min={startDate || undefined} required className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500" />
        </div>
        <button type="submit" disabled={loading} className="inline-flex h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-blue-700 px-5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto lg:min-w-[190px]">
          {loading ? <LoaderCircle size={16} className="animate-spin" /> : <Search size={16} />}
          {loading ? "Generating report..." : "Generate income statement"}
        </button>
      </form>

      {error && <div role="alert" className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
      {!report && !loading && !error && (
        <ReportEmptyState title="No income statement generated" description="Choose a start date and end date to calculate revenue, expenses and net income." />
      )}

      {report && (
        <div className="w-full min-w-0 space-y-6 p-4 sm:p-5">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Income Statement</h3>
            <p className="mt-1 text-xs text-slate-500">{formatReportDate(report.period.start_date)} – {formatReportDate(report.period.end_date)}</p>
          </div>

          {report.currencies.map((item) => {
            const revenueRows: StatementRow[] = item.revenue_accounts.map((row) => ({
              id: row.account_id,
              code: row.code,
              name: row.name,
              amount: row.amount,
            }));
            const expenseRows: StatementRow[] = item.expense_accounts.map((row) => ({
              id: row.account_id,
              code: row.code,
              name: row.name,
              amount: row.amount,
            }));

            return (
              <section key={item.currency} className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/40 p-3 sm:p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-bold text-slate-900">{item.currency} income statement</h4>
                  <span className="rounded-full bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">{revenueRows.length + expenseRows.length} accounts</span>
                </div>

                <StatementAccountSection title="Revenue" rows={revenueRows} currency={item.currency} totalLabel="Total revenue" totalAmount={item.total_revenue} emptyMessage="No revenue activity in this period." />
                <StatementAccountSection title="Expenses" rows={expenseRows} currency={item.currency} totalLabel="Total expenses" totalAmount={item.total_expenses} emptyMessage="No expense activity in this period." />

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <StatementMetric label="Total revenue" amount={item.total_revenue} currency={item.currency} />
                  <StatementMetric label="Total expenses" amount={item.total_expenses} currency={item.currency} />
                  <StatementMetric label="Net income" amount={item.net_income} currency={item.currency} emphasis />
                </div>
              </section>
            );
          })}

          <ReportBasisNotice value={report.report_basis} />
        </div>
      )}
    </div>
  );
}

function BalanceSheetReport({
  organizationId,
}: {
  organizationId: string;
}) {
  const [asOfDate, setAsOfDate] = useState(getLocalDateValue);
  const [report, setReport] = useState<BalanceSheetResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!asOfDate) {
      setError("Select an as-of date.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);
    try {
      const result = await fetchBalanceSheet(organizationId, asOfDate);
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate the balance sheet.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="w-full min-w-0">
      <div className="border-b border-slate-100 p-5">
        <h2 className="text-sm font-bold text-slate-900">Balance Sheet</h2>
        <p className="mt-1 text-xs text-slate-400">
          Review assets, liabilities and equity as of a selected date.
        </p>
      </div>

      <form onSubmit={handleGenerateReport} className="flex flex-col gap-4 border-b border-slate-100 bg-slate-50/60 p-5 sm:flex-row sm:items-end">
        <div className="w-full min-w-0 sm:max-w-xs">
          <label htmlFor="balance-sheet-date" className="mb-1.5 block text-xs font-semibold text-slate-600">Report as of</label>
          <input id="balance-sheet-date" type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} required className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500" />
        </div>
        <button type="submit" disabled={loading} className="inline-flex h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-blue-700 px-5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:min-w-[190px]">
          {loading ? <LoaderCircle size={16} className="animate-spin" /> : <Search size={16} />}
          {loading ? "Generating report..." : "Generate balance sheet"}
        </button>
      </form>

      {error && <div role="alert" className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
      {!report && !loading && !error && (
        <ReportEmptyState title="No balance sheet generated" description="Choose an as-of date to calculate the organization's assets, liabilities and equity." />
      )}

      {report && (
        <div className="w-full min-w-0 space-y-6 p-4 sm:p-5">
          <div>
            <h3 className="text-lg font-bold text-slate-900">Balance Sheet</h3>
            <p className="mt-1 text-xs text-slate-500">As of {formatReportDate(report.as_of_date)}</p>
          </div>

          {report.currencies.map((item) => {
            const assets: StatementRow[] = item.assets.accounts.map((row) => ({
              id: row.id,
              code: row.code,
              name: row.name,
              amount: row.balance,
            }));
            const liabilities: StatementRow[] = item.liabilities.accounts.map((row) => ({
              id: row.id,
              code: row.code,
              name: row.name,
              amount: row.balance,
            }));
            const equity: StatementRow[] = item.equity.accounts.map((row) => ({
              id: row.id,
              code: row.code,
              name: row.name,
              amount: row.balance,
            }));

            return (
              <section key={item.currency} className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/40 p-3 sm:p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-bold text-slate-900">{item.currency} balance sheet</h4>
                  {item.is_balanced ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700"><CheckCircle2 size={14} /> Balanced</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-700"><CircleAlert size={14} /> Out of balance</span>
                  )}
                </div>

                <StatementAccountSection title="Assets" rows={assets} currency={item.currency} totalLabel="Total assets" totalAmount={item.assets.total} emptyMessage="No asset balances as of this date." />
                <StatementAccountSection title="Liabilities" rows={liabilities} currency={item.currency} totalLabel="Total liabilities" totalAmount={item.liabilities.total} emptyMessage="No liability balances as of this date." />
                <StatementAccountSection title="Equity accounts" rows={equity} currency={item.currency} totalLabel="Equity account balances" totalAmount={item.equity.total} emptyMessage="No equity account balances as of this date." />

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <StatementMetric label="Cumulative unclosed earnings" amount={item.equity.cumulative_unclosed_earnings} currency={item.currency} />
                  <StatementMetric label="Total equity including unclosed earnings" amount={item.equity.total_including_unclosed_earnings} currency={item.currency} emphasis />
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <StatementMetric label="Total assets" amount={item.assets.total} currency={item.currency} />
                  <StatementMetric label="Liabilities and equity" amount={item.total_liabilities_and_equity} currency={item.currency} />
                  <StatementMetric label="Balance difference" amount={item.balance_difference} currency={item.currency} emphasis />
                </div>
              </section>
            );
          })}

          <ReportBasisNotice value={report.report_basis} />
          <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-600">
            <Landmark size={16} className="mt-0.5 shrink-0 text-slate-500" />
            <p>
              Cumulative unclosed earnings are included separately because year-end closing entries are not yet implemented. A balanced statement does not by itself confirm that all account classifications are correct.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}


export function AccountingReports({
  organizationId,
  accounts,
}: Props) {
  const [activeReport, setActiveReport] = useState<ReportTab>("ledger");

  return (
    <div className="w-full min-w-0">
      <div className="flex flex-wrap gap-x-5 border-b border-slate-100 px-5">
        <button
          type="button"
          onClick={() => setActiveReport("ledger")}
          className={`inline-flex items-center gap-2 border-b-2 py-4 text-xs font-semibold transition ${
            activeReport === "ledger"
              ? "border-blue-700 text-blue-700"
              : "border-transparent text-slate-400 hover:text-slate-700"
          }`}
        >
          <BookOpen size={15} />
          General Ledger
        </button>

        <button
          type="button"
          onClick={() => setActiveReport("trial-balance")}
          className={`inline-flex items-center gap-2 border-b-2 py-4 text-xs font-semibold transition ${
            activeReport === "trial-balance"
              ? "border-blue-700 text-blue-700"
              : "border-transparent text-slate-400 hover:text-slate-700"
          }`}
        >
          <Scale size={15} />
          Trial Balance
        </button>

        <button
          type="button"
          onClick={() => setActiveReport("income-statement")}
          className={`inline-flex items-center gap-2 border-b-2 py-4 text-xs font-semibold transition ${
            activeReport === "income-statement"
              ? "border-blue-700 text-blue-700"
              : "border-transparent text-slate-400 hover:text-slate-700"
          }`}
        >
          <TrendingUp size={15} />
          Income Statement
        </button>

        <button
          type="button"
          onClick={() => setActiveReport("balance-sheet")}
          className={`inline-flex items-center gap-2 border-b-2 py-4 text-xs font-semibold transition ${
            activeReport === "balance-sheet"
              ? "border-blue-700 text-blue-700"
              : "border-transparent text-slate-400 hover:text-slate-700"
          }`}
        >
          <Landmark size={15} />
          Balance Sheet
        </button>
      </div>

      {activeReport === "ledger" && (
        <LedgerReport organizationId={organizationId} accounts={accounts} />
      )}
      {activeReport === "trial-balance" && (
        <TrialBalanceReport organizationId={organizationId} />
      )}
      {activeReport === "income-statement" && (
        <IncomeStatementReport organizationId={organizationId} />
      )}
      {activeReport === "balance-sheet" && (
        <BalanceSheetReport organizationId={organizationId} />
      )}
    </div>
  );
}
