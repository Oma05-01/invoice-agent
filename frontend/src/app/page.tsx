
"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Building2,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileClock,
  FilePlus2,
  FileText,
  LayoutDashboard,
  MoreHorizontal,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  Users,
  X,
} from "lucide-react";
import { ProtectedRoute } from "@/components/protected-route";

type InvoiceStatus =
  | "Needs review"
  | "Pending approval"
  | "Approved"
  | "Rejected"
  | "Processing";

type Invoice = {
  id: string;
  vendor: string;
  initials: string;
  date: string;
  amount: string;
  status: InvoiceStatus;
  color: string;
};

const invoices: Invoice[] = [
  {
    id: "INV-2026-041",
    vendor: "ABC Engineering Ltd",
    initials: "AE",
    date: "Nov 06, 2026",
    amount: "₦537,500.00",
    status: "Needs review",
    color: "bg-blue-100 text-blue-700",
  },
  {
    id: "INV-2026-040",
    vendor: "Northstar Supplies",
    initials: "NS",
    date: "Nov 05, 2026",
    amount: "₦1,240,000.00",
    status: "Pending approval",
    color: "bg-violet-100 text-violet-700",
  },
  {
    id: "INV-2026-039",
    vendor: "Bluewave Technologies",
    initials: "BT",
    date: "Nov 05, 2026",
    amount: "₦285,000.00",
    status: "Approved",
    color: "bg-cyan-100 text-cyan-700",
  },
  {
    id: "INV-2026-038",
    vendor: "Meridian Services",
    initials: "MS",
    date: "Nov 04, 2026",
    amount: "₦860,000.00",
    status: "Needs review",
    color: "bg-orange-100 text-orange-700",
  },
  {
    id: "INV-2026-037",
    vendor: "Apex Industrial",
    initials: "AI",
    date: "Nov 03, 2026",
    amount: "₦415,750.00",
    status: "Rejected",
    color: "bg-rose-100 text-rose-700",
  },
  {
    id: "INV-2026-036",
    vendor: "Greenfield Logistics",
    initials: "GL",
    date: "Nov 02, 2026",
    amount: "₦1,080,000.00",
    status: "Approved",
    color: "bg-emerald-100 text-emerald-700",
  },
];

const statusStyles: Record<InvoiceStatus, string> = {
  "Needs review": "bg-amber-50 text-amber-700 ring-amber-200",
  "Pending approval": "bg-blue-50 text-blue-700 ring-blue-200",
  Approved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Rejected: "bg-rose-50 text-rose-700 ring-rose-200",
  Processing: "bg-violet-50 text-violet-700 ring-violet-200",
};

function StatusBadge({ status }: { status: InvoiceStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${statusStyles[status]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function UploadDialog({ onClose }: { onClose: () => void }) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [showNotice, setShowNotice] = useState(false);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <section
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-title"
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <FilePlus2 size={22} />
            </div>
            <h2 id="upload-title" className="text-lg font-semibold text-slate-900">
              Upload an invoice
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Select a supplier invoice in PDF format.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close upload dialog"
          >
            <X size={19} />
          </button>
        </div>

        <label className="mt-6 flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 px-5 py-9 text-center transition hover:border-blue-300 hover:bg-blue-50/40">
          <UploadCloud size={30} className="text-blue-600" />
          <span className="mt-3 text-sm font-semibold text-slate-800">
            Choose an invoice PDF
          </span>
          <span className="mt-1 text-xs text-slate-500">
            PDF documents only
          </span>
          <input
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(event) => {
              setSelectedFile(event.target.files?.[0] ?? null);
              setShowNotice(false);
            }}
          />
        </label>

        {selectedFile && (
          <div className="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 p-3">
            <FileText className="shrink-0 text-blue-600" size={21} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-800">
                {selectedFile.name}
              </p>
              <p className="text-xs text-slate-500">
                {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
            <CheckCircle2 size={18} className="text-emerald-600" />
          </div>
        )}

        <div className="mt-5 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-800">
          This is the frontend preview of the upload flow. The Django upload API
          has not been connected yet, so selecting a file does not send or store it.
        </div>

        {showNotice && (
          <p className="mt-3 text-sm text-slate-600">
            File selected locally. API integration is the next step.
          </p>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!selectedFile}
            onClick={() => setShowNotice(true)}
            className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Continue
          </button>
        </div>
      </section>
    </div>
  );
}

export default function Home() {
  const [search, setSearch] = useState("");
  const [selectedFilter, setSelectedFilter] = useState("All invoices");
  const [uploadOpen, setUploadOpen] = useState(false);

  const filters = [
    "All invoices",
    "Needs review",
    "Pending approval",
    "Approved",
  ];

  const filteredInvoices = useMemo(() => {
    const query = search.trim().toLowerCase();

    return invoices.filter((invoice) => {
      const matchesSearch =
        !query ||
        invoice.id.toLowerCase().includes(query) ||
        invoice.vendor.toLowerCase().includes(query) ||
        invoice.status.toLowerCase().includes(query);

      const matchesFilter =
        selectedFilter === "All invoices" ||
        invoice.status === selectedFilter;

      return matchesSearch && matchesFilter;
    });
  }, [search, selectedFilter]);

  const metrics = [
    {
      title: "Total invoices",
      value: "248",
      change: "+6.2%",
      description: "vs. last month",
      icon: FileText,
      iconStyle: "bg-blue-50 text-blue-700",
      trend: "up",
    },
    {
      title: "Awaiting review",
      value: "18",
      change: "Needs attention",
      description: "Invoices to review",
      icon: Clock3,
      iconStyle: "bg-amber-50 text-amber-700",
      trend: "neutral",
    },
    {
      title: "Pending approval",
      value: "7",
      change: "Awaiting decision",
      description: "Approval requests",
      icon: FileClock,
      iconStyle: "bg-violet-50 text-violet-700",
      trend: "neutral",
    },
    {
      title: "Approved this month",
      value: "196",
      change: "+12.8%",
      description: "vs. last month",
      icon: FileCheck2,
      iconStyle: "bg-emerald-50 text-emerald-700",
      trend: "up",
    },
  ];

  const navigation = [
    { label: "Overview", icon: LayoutDashboard, active: true },
    { label: "Invoices", icon: FileText, soon: true },
    { label: "Approvals", icon: ShieldCheck, soon: true },
    { label: "Vendors", icon: Building2, soon: true },
    { label: "Audit log", icon: Activity, soon: true },
  ];

  return (
    <ProtectedRoute>
      <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
      <div className="flex min-h-screen">
        {/* Sidebar */}
        <aside className="hidden w-[250px] shrink-0 flex-col bg-[#111b2e] text-white lg:flex">
          <div className="flex h-[76px] items-center gap-3 border-b border-white/10 px-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600">
              <span className="text-sm font-bold tracking-tight">F1</span>
            </div>
            <div>
              <p className="text-[16px] font-bold tracking-wide">FIN-01</p>
              <p className="text-[10px] tracking-[0.16em] text-slate-400">
                FINANCE OPERATIONS
              </p>
            </div>
          </div>

          <div className="px-4 pt-7">
            <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
              Workspace
            </p>

            <nav className="space-y-1">
              {navigation.map((item) => {
                const Icon = item.icon;

                return (
                  <button
                    type="button"
                    key={item.label}
                    disabled={item.soon}
                    title={
                      item.soon
                        ? `${item.label} workspace is coming next`
                        : item.label
                    }
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                      item.active
                        ? "bg-blue-600 font-medium text-white shadow-lg shadow-blue-950/20"
                        : "cursor-not-allowed text-slate-400"
                    }`}
                  >
                    <Icon size={18} />
                    <span className="flex-1">{item.label}</span>
                    {item.soon && (
                      <span className="text-[9px] font-medium uppercase tracking-wide text-slate-500">
                        Soon
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>
          </div>

          <div className="mt-9 px-4">
            <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
              Organization
            </p>

            <button
              type="button"
              disabled
              className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-400"
            >
              <Users size={18} />
              Team members
            </button>
          </div>

          <div className="mt-auto space-y-4 p-4">
            <div className="rounded-xl border border-white/10 bg-white/[0.04] p-4">
              <div className="flex items-center gap-2 text-blue-300">
                <CircleHelp size={17} />
                <span className="text-xs font-semibold text-slate-200">
                  Need help?
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-400">
                Your invoice processing workspace, all in one place.
              </p>
            </div>

            <div className="flex items-center gap-3 border-t border-white/10 px-2 pt-4">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold">
                FO
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold">Finance Operator</p>
                <p className="truncate text-[10px] text-slate-400">
                  Demo workspace
                </p>
              </div>
              <MoreHorizontal size={18} className="text-slate-400" />
            </div>
          </div>
        </aside>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          {/* Top bar */}
          <header className="flex h-[76px] items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
            <div className="min-w-0">
              <p className="text-xs text-slate-400">
                Finance operations <span className="mx-1">/</span>{" "}
                <span className="font-medium text-slate-600">Overview</span>
              </p>
              <p className="mt-1 truncate text-sm font-semibold text-slate-800">
                ABC Holdings
              </p>
            </div>

            <div className="flex items-center gap-3 sm:gap-5">
              <div className="relative hidden md:block">
                <Search
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search invoices..."
                  className="h-10 w-56 rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:bg-white"
                  aria-label="Search invoices"
                />
              </div>

              <button
                type="button"
                className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100"
                aria-label="Notifications"
              >
                <Bell size={19} />
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full border-2 border-white bg-rose-500" />
              </button>

              <div className="hidden h-8 w-px bg-slate-200 sm:block" />

              <button
                type="button"
                className="flex items-center gap-2"
                aria-label="Organization profile"
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                  FO
                </div>
                <div className="hidden text-left sm:block">
                  <p className="text-xs font-semibold text-slate-800">
                    Finance Operator
                  </p>
                  <p className="text-[10px] text-slate-400">Administrator</p>
                </div>
                <ChevronDown size={15} className="hidden text-slate-400 sm:block" />
              </button>
            </div>
          </header>

          <div className="mx-auto max-w-[1600px] p-5 sm:p-8">
            {/* Page heading */}
            <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <div>
                <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
                  <Sparkles size={12} />
                  Finance overview
                </div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-[28px]">
                  Good morning
                </h1>
                <p className="mt-1 text-sm text-slate-500">
                  Here&apos;s what&apos;s happening with your invoices today.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800"
              >
                <FilePlus2 size={17} />
                Upload invoice
              </button>
            </div>

            {/* Sample-data notice */}
            <div className="mb-6 flex items-center gap-2 rounded-lg border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs text-blue-800">
              <Activity size={15} className="shrink-0" />
              <span>
                <strong>Demo workspace:</strong> figures and invoices on this
                screen are sample data. Live Django API integration comes next.
              </span>
            </div>

            {/* Metric cards */}
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {metrics.map((metric) => {
                const Icon = metric.icon;

                return (
                  <div
                    key={metric.title}
                    className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/30"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-medium text-slate-500">
                          {metric.title}
                        </p>
                        <p className="mt-3 text-[30px] font-bold tracking-tight text-slate-900">
                          {metric.value}
                        </p>
                      </div>
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-xl ${metric.iconStyle}`}
                      >
                        <Icon size={19} />
                      </div>
                    </div>
                    <div className="mt-3 flex items-center gap-1.5 text-[11px]">
                      {metric.trend === "up" && (
                        <ArrowUpRight size={14} className="text-emerald-600" />
                      )}
                      <span
                        className={
                          metric.trend === "up"
                            ? "font-semibold text-emerald-700"
                            : "font-medium text-slate-600"
                        }
                      >
                        {metric.change}
                      </span>
                      <span className="text-slate-400">{metric.description}</span>
                    </div>
                  </div>
                );
              })}
            </section>

            {/* Main dashboard columns */}
            <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.85fr)]">
              {/* Recent invoices */}
              <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-200/30">
                <div className="flex flex-col justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center">
                  <div>
                    <h2 className="text-sm font-bold text-slate-900">
                      Recent invoices
                    </h2>
                    <p className="mt-1 text-xs text-slate-400">
                      Track the latest invoice activity.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled
                    className="inline-flex cursor-not-allowed items-center gap-1 text-xs font-semibold text-blue-700 opacity-70"
                    title="Full invoice listing is coming next"
                  >
                    View all invoices <ArrowRight size={14} />
                  </button>
                </div>

                {/* Mobile search */}
                <div className="border-b border-slate-100 px-5 py-3 md:hidden">
                  <div className="relative">
                    <Search
                      size={15}
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                    />
                    <input
                      type="search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search invoices..."
                      className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs outline-none focus:border-blue-400"
                      aria-label="Search invoices"
                    />
                  </div>
                </div>

                {/* Invoice filters */}
                <div className="flex gap-5 overflow-x-auto border-b border-slate-100 px-5">
                  {filters.map((filter) => (
                    <button
                      type="button"
                      key={filter}
                      onClick={() => setSelectedFilter(filter)}
                      className={`whitespace-nowrap border-b-2 py-3 text-xs font-medium transition ${
                        selectedFilter === filter
                          ? "border-blue-700 text-blue-700"
                          : "border-transparent text-slate-400 hover:text-slate-700"
                      }`}
                    >
                      {filter}
                    </button>
                  ))}
                </div>

                {/* Invoice table */}
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[690px] border-collapse text-left">
                    <thead>
                      <tr className="bg-slate-50/80">
                        <th className="px-5 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Invoice / Supplier
                        </th>
                        <th className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Date
                        </th>
                        <th className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Amount
                        </th>
                        <th className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Status
                        </th>
                        <th className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {filteredInvoices.map((invoice) => (
                        <tr
                          key={invoice.id}
                          className="transition hover:bg-slate-50/70"
                        >
                          <td className="px-5 py-4">
                            <div className="flex items-center gap-3">
                              <div
                                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold ${invoice.color}`}
                              >
                                {invoice.initials}
                              </div>
                              <div className="min-w-0">
                                <p className="whitespace-nowrap text-xs font-semibold text-slate-800">
                                  {invoice.id}
                                </p>
                                <p className="mt-1 truncate text-[11px] text-slate-400">
                                  {invoice.vendor}
                                </p>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-4 text-xs text-slate-500">
                            {invoice.date}
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap text-xs font-semibold text-slate-800">
                            {invoice.amount}
                          </td>
                          <td className="px-4 py-4">
                            <StatusBadge status={invoice.status} />
                          </td>
                          <td className="px-4 py-4 text-right">
                            <button
                              type="button"
                              disabled
                              title="Invoice details workspace is coming next"
                              className="cursor-not-allowed rounded-lg p-1.5 text-slate-400 opacity-50"
                              aria-label={`More actions for ${invoice.id}`}
                            >
                              <MoreHorizontal size={17} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {filteredInvoices.length === 0 && (
                    <div className="px-5 py-12 text-center">
                      <Search className="mx-auto text-slate-300" size={25} />
                      <p className="mt-3 text-sm font-medium text-slate-600">
                        No matching invoices
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        Try another search or filter.
                      </p>
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-100 px-5 py-3">
                  <p className="text-[10px] text-slate-400">
                    Showing {filteredInvoices.length} of {invoices.length} sample invoices
                  </p>
                </div>
              </section>

              {/* Activity */}
              <div className="space-y-6">
                <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/30">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">
                        Recent activity
                      </h2>
                      <p className="mt-1 text-xs text-slate-400">
                        What&apos;s happening in your workspace.
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled
                      className="cursor-not-allowed rounded-lg p-1.5 text-slate-400 opacity-50"
                      aria-label="Activity options"
                    >
                      <MoreHorizontal size={18} />
                    </button>
                  </div>

                  <div className="mt-5 space-y-5">
                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                        <CheckCircle2 size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs leading-5 text-slate-700">
                          <strong className="font-semibold">INV-2026-039</strong>{" "}
                          was approved.
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          24 minutes ago
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-700">
                        <Sparkles size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs leading-5 text-slate-700">
                          AI extraction completed for{" "}
                          <strong className="font-semibold">INV-2026-041</strong>.
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          1 hour ago
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-700">
                        <FileText size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs leading-5 text-slate-700">
                          New invoice received from{" "}
                          <strong className="font-semibold">
                            ABC Engineering Ltd
                          </strong>.
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          2 hours ago
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-rose-50 text-rose-700">
                        <X size={16} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs leading-5 text-slate-700">
                          <strong className="font-semibold">INV-2026-037</strong>{" "}
                          was returned for correction.
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          Yesterday
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 border-t border-slate-100 pt-4">
                    <p className="text-[10px] text-slate-400">
                      Sample activity for demonstration
                    </p>
                  </div>
                </section>

                {/* Workflow overview */}
                <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/30">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">
                        Invoice workflow
                      </h2>
                      <p className="mt-1 text-xs text-slate-400">
                        How invoices move through FIN-01.
                      </p>
                    </div>
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                      <Activity size={17} />
                    </div>
                  </div>

                  <div className="mt-5 space-y-0">
                    <div className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-50 text-blue-700">
                          <UploadCloud size={14} />
                        </div>
                        <div className="h-7 w-px bg-slate-200" />
                      </div>
                      <div className="pb-4">
                        <p className="text-xs font-semibold text-slate-800">
                          Document received
                        </p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          Invoice uploaded
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-50 text-violet-700">
                          <Sparkles size={14} />
                        </div>
                        <div className="h-7 w-px bg-slate-200" />
                      </div>
                      <div className="pb-4">
                        <p className="text-xs font-semibold text-slate-800">
                          AI extraction and validation
                        </p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          Information captured and checked
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-50 text-amber-700">
                          <FileText size={14} />
                        </div>
                        <div className="h-7 w-px bg-slate-200" />
                      </div>
                      <div className="pb-4">
                        <p className="text-xs font-semibold text-slate-800">
                          Human review
                        </p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          Corrections and verification
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                        <ShieldCheck size={14} />
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-slate-800">
                          Financial approval
                        </p>
                        <p className="mt-0.5 text-[10px] text-slate-400">
                          Independent approval decision
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 rounded-lg bg-slate-50 p-3">
                    <p className="text-[10px] leading-5 text-slate-500">
                      AI assists with extraction. Financial rules and authorized
                      employees retain control of validation and approval.
                    </p>
                  </div>
                </section>
              </div>
            </div>

            <footer className="mt-8 flex flex-col justify-between gap-2 border-t border-slate-200 pt-5 text-[10px] text-slate-400 sm:flex-row">
              <p>FIN-01 Finance Operations Platform</p>
              <p>AI-assisted processing · Human-controlled approvals</p>
            </footer>
          </div>
        </div>
      </div>

      {uploadOpen && <UploadDialog onClose={() => setUploadOpen(false)} />}
    </main>
    </ProtectedRoute>
   
  );
}
