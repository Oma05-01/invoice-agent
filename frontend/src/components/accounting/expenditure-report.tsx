"use client";

import { useState, type FormEvent } from "react";
import { CalendarDays, LoaderCircle, Search } from "lucide-react";

import { fetchSpendReport } from "@/lib/insights";
import type {
  SpendDimension,
  SpendReportResponse,
  SpendReportRow,
} from "@/types/insights";

type ExpenditureReportProps = {
  organizationId: string;
};

function getLocalDateValue(): string {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getMonthStartValue(): string {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}-01`;
}

function formatSpendAmount(value: string, currency: string): string {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!match) return `${currency} ${value}`;

  const [, sign, whole, fraction = ""] = match;
  const groupedWhole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimalPart = fraction.padEnd(2, "0");
  return `${sign === "-" ? "-" : ""}${currency} ${groupedWhole}.${decimalPart}`;
}

function formatReportDate(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatMonth(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("en-NG", {
    month: "long",
    year: "numeric",
  }).format(date);
}

function getRowDetails(
  row: SpendReportRow,
  dimension: SpendDimension,
): { title: string; detail: string } {
  if (dimension === "vendor" && "vendor_name" in row) {
    return {
      title: row.vendor_name,
      detail: row.vendor_id ? `Vendor ID: ${row.vendor_id}` : "No vendor assigned",
    };
  }

  if (dimension === "account" && "account_name" in row) {
    return {
      title: row.account_name,
      detail: `Account ${row.account_code}`,
    };
  }

  if (dimension === "month" && "month" in row) {
    return {
      title: formatMonth(row.month),
      detail: row.month,
    };
  }

  return { title: "Unrecognised report row", detail: "" };
}

function ReportEmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-12 text-center">
      <CalendarDays size={24} className="mx-auto text-slate-400" />
      <p className="mt-3 text-sm font-semibold text-slate-700">{title}</p>
      <p className="mx-auto mt-1 max-w-lg text-xs leading-5 text-slate-500">
        {description}
      </p>
    </div>
  );
}

function SpendCurrencySection({
  currencyReport,
  dimension,
}: {
  currencyReport: SpendReportResponse["currencies"][number];
  dimension: SpendDimension;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="grid gap-4 border-b border-slate-100 p-5 sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium text-slate-500">Total expenditure</p>
          <p className="mt-2 break-words text-2xl font-bold tabular-nums text-slate-900">
            {formatSpendAmount(currencyReport.total_expenditure, currencyReport.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Across {currencyReport.group_count.toLocaleString("en-NG")} groups
          </p>
        </div>
        <div className="sm:text-right">
          <p className="text-xs font-medium text-slate-500">Displayed groups</p>
          <p className="mt-2 text-2xl font-bold tabular-nums text-slate-900">
            {currencyReport.returned_group_count.toLocaleString("en-NG")}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {currencyReport.is_truncated
              ? `Visible-row subtotal: ${formatSpendAmount(currencyReport.returned_expenditure, currencyReport.currency)}`
              : "All report groups are displayed"}
          </p>
        </div>
      </div>

      {currencyReport.rows.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-slate-500">
          No expenditure was recorded in this currency for the selected period.
        </div>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-semibold">
                    {dimension === "vendor"
                      ? "Vendor"
                      : dimension === "account"
                        ? "Expense account"
                        : "Accounting month"}
                  </th>
                  <th className="px-5 py-3 text-right font-semibold">Expenditure</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {currencyReport.rows.map((row, index) => {
                  const details = getRowDetails(row, dimension);
                  const key =
                    "vendor_id" in row
                      ? row.vendor_id ?? `unattributed-${index}`
                      : "account_id" in row
                        ? row.account_id
                        : row.month;

                  return (
                    <tr key={key}>
                      <td className="px-5 py-4">
                        <p className="font-semibold text-slate-800">{details.title}</p>
                        <p className="mt-1 text-xs text-slate-400">{details.detail}</p>
                      </td>
                      <td className="whitespace-nowrap px-5 py-4 text-right font-semibold tabular-nums text-slate-900">
                        {formatSpendAmount(row.amount, currencyReport.currency)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-slate-100 md:hidden">
            {currencyReport.rows.map((row, index) => {
              const details = getRowDetails(row, dimension);
              const key =
                "vendor_id" in row
                  ? row.vendor_id ?? `unattributed-${index}`
                  : "account_id" in row
                    ? row.account_id
                    : row.month;

              return (
                <div key={key} className="flex items-start justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <p className="break-words text-sm font-semibold text-slate-800">
                      {details.title}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">{details.detail}</p>
                  </div>
                  <p className="shrink-0 text-right text-sm font-semibold tabular-nums text-slate-900">
                    {formatSpendAmount(row.amount, currencyReport.currency)}
                  </p>
                </div>
              );
            })}
          </div>
        </>
      )}

      {currencyReport.is_truncated && (
        <div className="border-t border-amber-100 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-800">
          This result is limited to the configured number of groups. The total expenditure above includes all groups; the displayed rows are only the returned subset.
        </div>
      )}
    </section>
  );
}

export function ExpenditureReport({
  organizationId,
}: ExpenditureReportProps) {
  const [dimension, setDimension] = useState<SpendDimension>("vendor");
  const [startDate, setStartDate] = useState(getMonthStartValue);
  const [endDate, setEndDate] = useState(getLocalDateValue);
  const [currency, setCurrency] = useState("");
  const [limit, setLimit] = useState("20");
  const [report, setReport] = useState<SpendReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleGenerateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const result = await fetchSpendReport(organizationId, {
        dimension,
        startDate,
        endDate,
        limit: Number(limit),
        currency: currency.trim() || undefined,
      });
      setReport(result);
    } catch (reportError) {
      setReport(null);
      setError(
        reportError instanceof Error
          ? reportError.message
          : "Unable to generate the expenditure report.",
      );
    } finally {
      setLoading(false);
    }
  }

  function clearReport() {
    setReport(null);
    setError("");
  }

  return (
    <div className="space-y-5 p-4 sm:p-5">
      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-5">
          <h2 className="text-sm font-bold text-slate-900">Expenditure Analysis</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Analyse posted expenditure by vendor, expense account or accounting month. Amounts are calculated from the organisation&apos;s accounting journal.
          </p>
        </div>

        <form onSubmit={handleGenerateReport} className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-6">
          <div className="min-w-0 sm:col-span-2 xl:col-span-2">
            <label htmlFor="spend-dimension" className="mb-1.5 block text-xs font-semibold text-slate-600">
              Group expenditure by
            </label>
            <select
              id="spend-dimension"
              value={dimension}
              onChange={(event) => {
                setDimension(event.target.value as SpendDimension);
                clearReport();
              }}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
            >
              <option value="vendor">Vendor</option>
              <option value="account">Expense account</option>
              <option value="month">Month</option>
            </select>
          </div>

          <div className="min-w-0">
            <label htmlFor="spend-start-date" className="mb-1.5 block text-xs font-semibold text-slate-600">
              Start date
            </label>
            <input
              id="spend-start-date"
              type="date"
              value={startDate}
              onChange={(event) => {
                setStartDate(event.target.value);
                clearReport();
              }}
              max={endDate || undefined}
              required
              className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
            />
          </div>

          <div className="min-w-0">
            <label htmlFor="spend-end-date" className="mb-1.5 block text-xs font-semibold text-slate-600">
              End date
            </label>
            <input
              id="spend-end-date"
              type="date"
              value={endDate}
              onChange={(event) => {
                setEndDate(event.target.value);
                clearReport();
              }}
              min={startDate || undefined}
              required
              className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
            />
          </div>

          <div className="min-w-0">
            <label htmlFor="spend-currency" className="mb-1.5 block text-xs font-semibold text-slate-600">
              Currency
            </label>
            <input
              id="spend-currency"
              type="text"
              value={currency}
              onChange={(event) => {
                setCurrency(event.target.value.toUpperCase().slice(0, 3));
                clearReport();
              }}
              placeholder="All currencies"
              maxLength={3}
              autoCapitalize="characters"
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm uppercase outline-none focus:border-blue-500"
            />
          </div>

          <div className="min-w-0">
            <label htmlFor="spend-limit" className="mb-1.5 block text-xs font-semibold text-slate-600">
              Groups per currency
            </label>
            <select
              id="spend-limit"
              value={limit}
              onChange={(event) => {
                setLimit(event.target.value);
                clearReport();
              }}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
            >
              <option value="10">10</option>
              <option value="20">20</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </div>

          <div className="flex items-end sm:col-span-2 xl:col-span-6">
            <button
              type="submit"
              disabled={loading || !startDate || !endDate || startDate > endDate || (currency.length > 0 && !/^[A-Z]{3}$/.test(currency))}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:min-w-[210px]"
            >
              {loading ? <LoaderCircle size={16} className="animate-spin" /> : <Search size={16} />}
              {loading ? "Generating report..." : "Generate expenditure report"}
            </button>
          </div>
        </form>
      </section>

      {error && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {!report && !loading && !error && (
        <ReportEmptyState
          title="No expenditure report generated"
          description="Choose a reporting period and grouping dimension, then generate a report to review expenditure from posted accounting activity."
        />
      )}

      {report && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-lg font-bold text-slate-900">Expenditure breakdown</h3>
              <p className="mt-1 text-xs text-slate-500">
                {formatReportDate(report.period.start_date)} – {formatReportDate(report.period.end_date)}
              </p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600">
              Grouped by {report.dimension}
            </span>
          </div>

          {report.currencies.map((currencyReport) => (
            <SpendCurrencySection
              key={currencyReport.currency}
              currencyReport={currencyReport}
              dimension={report.dimension}
            />
          ))}

          <div className="rounded-xl border border-blue-100 bg-blue-50/60 p-4">
            <p className="text-xs font-bold uppercase tracking-wide text-blue-800">Report basis</p>
            <p className="mt-2 text-xs leading-6 text-blue-900">{report.report_basis}</p>
          </div>
        </div>
      )}
    </div>
  );
}
