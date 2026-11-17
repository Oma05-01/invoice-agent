
"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  AccountSpendRow,
  FinancialAssistantReportArtifact,
  FinancialReportCurrency,
  FinancialSpendReport,
  MonthlySpendRow,
  VendorSpendRow,
} from "@/types/financial-assistant";

type SpendRow =
  | VendorSpendRow
  | AccountSpendRow
  | MonthlySpendRow;

type CurrencyReport =
  | FinancialReportCurrency<VendorSpendRow>
  | FinancialReportCurrency<AccountSpendRow>
  | FinancialReportCurrency<MonthlySpendRow>;

type Props = {
  artifacts: FinancialAssistantReportArtifact[];
};

type ChartPoint = {
  label: string;
  sortKey: string;
  amount: number;
};

function formatAmount(value: string | number, currency: string): string {
  const amount = typeof value === "number" ? value : Number(value);

  if (!Number.isFinite(amount)) return "—";

  if (currency === "UNKNOWN") {
    return `${new Intl.NumberFormat("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount)} (unknown currency)`;
  }

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-NG", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatDate(value: string): string {
  const date = new Date(`${value}T12:00:00`);

  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatMonth(value: string): string {
  const date = new Date(`${value}T12:00:00`);

  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("en-NG", {
    month: "short",
    year: "2-digit",
  }).format(date);
}

function getDimensionLabel(dimension: FinancialSpendReport["dimension"]): string {
  switch (dimension) {
    case "vendor":
      return "Vendor expenditure";
    case "account":
      return "Expenditure by account";
    case "month":
      return "Monthly expenditure";
  }
}

function getRowLabel(
  dimension: FinancialSpendReport["dimension"],
  row: SpendRow,
): string {
  switch (dimension) {
    case "vendor":
      return (row as VendorSpendRow).vendor_name;

    case "account": {
      const account = row as AccountSpendRow;
      return `${account.account_code} · ${account.account_name}`;
    }

    case "month":
      return formatMonth((row as MonthlySpendRow).month);
  }
}

function getChartData(
  report: FinancialSpendReport,
  currencyReport: CurrencyReport,
): ChartPoint[] {
  const points = currencyReport.rows.map((row) => {
    const monthlyDate =
      report.dimension === "month"
        ? (row as MonthlySpendRow).month
        : "";

    return {
      label: getRowLabel(report.dimension, row),
      sortKey: monthlyDate,
      amount: Number(row.amount),
    };
  });

  if (report.dimension === "month") {
    points.sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }

  return points;
}

function CurrencyReportSection({
  report,
  currencyReport,
}: {
  report: FinancialSpendReport;
  currencyReport: CurrencyReport;
}) {
  const chartData = getChartData(report, currencyReport);
  const chartHeight = Math.max(240, chartData.length * 38);

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-slate-900">
          {currencyReport.currency}
        </h4>
        <span className="text-[10px] text-slate-400">
          {currencyReport.group_count} groups
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-[10px] text-slate-500">Net expenditure</p>
          <p className="mt-1 break-words text-sm font-bold text-slate-900">
            {formatAmount(
              currencyReport.total_expenditure,
              currencyReport.currency,
            )}
          </p>
        </div>

        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-[10px] text-slate-500">Gross debits</p>
          <p className="mt-1 break-words text-sm font-semibold text-slate-800">
            {formatAmount(
              currencyReport.gross_debits,
              currencyReport.currency,
            )}
          </p>
        </div>

        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-[10px] text-slate-500">Gross credits</p>
          <p className="mt-1 break-words text-sm font-semibold text-slate-800">
            {formatAmount(
              currencyReport.gross_credits,
              currencyReport.currency,
            )}
          </p>
        </div>

        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-[10px] text-slate-500">Journal entries</p>
          <p className="mt-1 text-sm font-semibold text-slate-800">
            {currencyReport.journal_count.toLocaleString("en-NG")}
          </p>
        </div>
      </div>

      {chartData.length > 0 ? (
        <div>
          <h5 className="mb-2 text-xs font-semibold text-slate-700">
            {getDimensionLabel(report.dimension)}
          </h5>

          <div style={{ width: "100%", height: chartHeight }}>
            <ResponsiveContainer width="100%" height="100%">
              {report.dimension === "month" ? (
                <LineChart
                  data={chartData}
                  margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10 }}
                    minTickGap={20}
                  />
                  <YAxis
                    tick={{ fontSize: 10 }}
                    tickFormatter={formatCompact}
                    width={55}
                  />
                  <Tooltip
                    formatter={(value) =>
                      formatAmount(Number(value), currencyReport.currency)
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="amount"
                    name="Net expenditure"
                    stroke="#2563eb"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              ) : (
                <BarChart
                  data={chartData}
                  layout="vertical"
                  margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    horizontal={false}
                  />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 10 }}
                    tickFormatter={formatCompact}
                  />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={145}
                    tick={{ fontSize: 10 }}
                  />
                  <Tooltip
                    formatter={(value) =>
                      formatAmount(Number(value), currencyReport.currency)
                    }
                  />
                  <Bar
                    dataKey="amount"
                    name="Net expenditure"
                    fill="#2563eb"
                    radius={[0, 5, 5, 0]}
                  />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <p className="rounded-lg bg-slate-50 p-5 text-center text-xs text-slate-500">
          No grouped expenditure rows were returned for this currency.
        </p>
      )}

      {chartData.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="py-2 pr-3 font-semibold">Group</th>
                <th className="py-2 pr-3 text-right font-semibold">Net</th>
                <th className="py-2 pr-3 text-right font-semibold">Debits</th>
                <th className="py-2 pr-3 text-right font-semibold">Credits</th>
                <th className="py-2 text-right font-semibold">Journals</th>
              </tr>
            </thead>
            <tbody>
              {currencyReport.rows.map((row, index) => (
                <tr
                  key={`${chartData[index]?.label ?? "row"}-${index}`}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="max-w-[150px] truncate py-2 pr-3 font-medium text-slate-700">
                    {getRowLabel(report.dimension, row)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right text-slate-800">
                    {formatAmount(row.amount, currencyReport.currency)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right text-slate-500">
                    {formatAmount(row.gross_debits, currencyReport.currency)}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right text-slate-500">
                    {formatAmount(row.gross_credits, currencyReport.currency)}
                  </td>
                  <td className="py-2 text-right text-slate-500">
                    {row.journal_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {currencyReport.is_truncated && (
        <p className="text-[10px] leading-4 text-amber-700">
          Showing {currencyReport.returned_group_count} of{" "}
          {currencyReport.group_count} groups. The report is truncated to its
          configured row limit.
        </p>
      )}

      <p className="text-[10px] text-slate-400">
        {currencyReport.journal_line_count.toLocaleString("en-NG")} expense
        journal lines included
      </p>
    </section>
  );
}

export function FinancialReportPanel({ artifacts }: Props) {
  const reports = [...artifacts].reverse();

  return (
    <aside
      className="flex min-h-[420px] min-w-0 flex-col rounded-xl border border-slate-200 bg-slate-50"
      aria-label="Financial reports"
    >
      <header className="border-b border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">
          Financial reports
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Structured results retrieved by the assistant.
        </p>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {reports.length === 0 ? (
          <div className="flex min-h-[340px] flex-col items-center justify-center px-5 text-center">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <span className="text-lg">↗</span>
            </div>
            <p className="mt-3 text-sm font-semibold text-slate-700">
              No report generated yet
            </p>
            <p className="mt-1 max-w-xs text-xs leading-5 text-slate-500">
              Ask the assistant to retrieve expenditure by vendor, account or
              month. Its structured report will appear here.
            </p>
          </div>
        ) : (
          reports.map((artifact, index) => (
            <section key={`${artifact.tool}-${index}`} className="space-y-3">
              <div className="flex items-center justify-between gap-2 px-1">
                <h4 className="text-xs font-semibold text-slate-700">
                  {index === 0 ? "Latest report" : "Earlier report"}
                </h4>
                <span className="text-[10px] text-slate-400">
                  {formatDate(artifact.report.period.start_date)} –{" "}
                  {formatDate(artifact.report.period.end_date)}
                </span>
              </div>

              {artifact.report.currencies.length === 0 ? (
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <p className="text-xs text-slate-600">
                    No currency groups were returned for this reporting
                    period.
                  </p>
                </div>
              ) : (
                artifact.report.currencies.map((currencyReport, currencyIndex) => (
                  <CurrencyReportSection
                    key={`${currencyReport.currency}-${currencyIndex}`}
                    report={artifact.report}
                    currencyReport={currencyReport}
                  />
                ))
              )}

              <p className="px-1 text-[10px] leading-4 text-slate-400">
                {artifact.report.report_basis}
              </p>
            </section>
          ))
        )}
      </div>
    </aside>
  );
}

