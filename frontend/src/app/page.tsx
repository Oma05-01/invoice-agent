"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  BookOpen,
  Building2,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileClock,
  FileText,
  LayoutDashboard,
  LogOut,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { useAuth } from "@/components/auth-provider";
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

// These records are deliberately retained as clearly labelled UI sample data.
// The live invoice workspace is available at /invoices.
const sampleInvoices: Invoice[] = [
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

function formatRole(role?: string | null) {
  if (!role) return "Organization member";

  return role
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

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

export default function Home() {
  const { user, logout } = useAuth();
  const [search, setSearch] = useState("");
  const [selectedFilter, setSelectedFilter] = useState("All invoices");
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  // The authenticated user's first organization is used as the overview tenant.
  // The invoice and accounting workspaces provide their own organization selector.
  const activeMembership = user?.organizations?.[0] ?? null;
  const organizationName = activeMembership?.name ?? "No organization assigned";
  const displayName =
    [user?.first_name, user?.last_name].filter(Boolean).join(" ") ||
    user?.username ||
    "Signed-in user";
  const roleLabel = formatRole(activeMembership?.role);
  const initials =
    [user?.first_name?.[0], user?.last_name?.[0]]
      .filter(Boolean)
      .join("")
      .toUpperCase() ||
    user?.username?.slice(0, 2).toUpperCase() ||
    "U";

  const filters = [
    "All invoices",
    "Needs review",
    "Pending approval",
    "Approved",
  ];

  const filteredInvoices = useMemo(() => {
    const query = search.trim().toLowerCase();

    return sampleInvoices.filter((invoice) => {
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

  const navigation: Array<{
    label: string;
    href?: string;
    icon: LucideIcon;
    active?: boolean;
    soon?: boolean;
  }> = [
    { label: "Overview", href: "/", icon: LayoutDashboard, active: true },
    { label: "Invoices", href: "/invoices", icon: FileText, active: false },
    { label: "Accounting", href: "/accounting", icon: BookOpen, active: false },
    { label: "Approvals", icon: ShieldCheck, soon: true },
    { label: "Vendors", icon: Building2, soon: true },
    { label: "Audit log", icon: Activity, soon: true },
  ];

  async function handleLogout() {
    setIsLoggingOut(true);
    setLogoutError(null);

    try {
      await logout();
      // ProtectedRoute handles the unauthenticated redirect after auth state clears.
    } catch {
      setLogoutError("We couldn't sign you out. Please try again.");
      setIsLoggingOut(false);
    }
  }

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

              <nav className="space-y-1" aria-label="Main navigation">
                {navigation.map((item) => {
                  const Icon = item.icon;
                  const className = `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                    item.active
                      ? "bg-blue-600 font-medium text-white shadow-lg shadow-blue-950/20"
                      : item.soon
                        ? "cursor-not-allowed text-slate-500"
                        : "text-slate-300 hover:bg-white/5 hover:text-white"
                  }`;

                  if (item.soon) {
                    return (
                      <button
                        type="button"
                        key={item.label}
                        disabled
                        title={`${item.label} workspace is not available yet`}
                        className={className}
                      >
                        <Icon size={18} />
                        <span className="flex-1">{item.label}</span>
                        <span className="text-[9px] font-medium uppercase tracking-wide text-slate-500">
                          Soon
                        </span>
                      </button>
                    );
                  }

                  return (
                    <Link
                      href={item.href ?? "/"}
                      key={item.label}
                      aria-current={item.active ? "page" : undefined}
                      className={className}
                    >
                      <Icon size={18} />
                      <span className="flex-1">{item.label}</span>
                    </Link>
                  );
                })}
              </nav>
            </div>

            <div className="mt-9 px-4">
              <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                Organization
              </p>
              <div className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-300">
                <Users size={18} />
                <span className="min-w-0 flex-1 truncate">Team members</span>
                <span className="text-[9px] font-medium uppercase tracking-wide text-slate-500">
                  Soon
                </span>
              </div>
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
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold">
                  {initials}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold">{displayName}</p>
                  <p className="truncate text-[10px] text-slate-400">
                    {roleLabel}
                  </p>
                </div>
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
                  {organizationName}
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
                    placeholder="Search sample invoices..."
                    className="h-10 w-56 rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:bg-white"
                    aria-label="Search sample invoices"
                  />
                </div>

                <button
                  type="button"
                  className="relative rounded-lg p-2 text-slate-400"
                  aria-label="Notifications (not connected)"
                  title="Notifications are not connected yet"
                  disabled
                >
                  <Bell size={19} />
                </button>

                <div className="hidden h-8 w-px bg-slate-200 sm:block" />

                <div className="relative">
                  <button
                    type="button"
                    onClick={() => {
                      setProfileMenuOpen((open) => !open);
                      setLogoutError(null);
                    }}
                    className="flex items-center gap-2 rounded-lg p-1.5 transition hover:bg-slate-50"
                    aria-label="Open account menu"
                    aria-expanded={profileMenuOpen}
                    aria-haspopup="menu"
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                      {initials}
                    </div>
                    <div className="hidden text-left sm:block">
                      <p className="max-w-36 truncate text-xs font-semibold text-slate-800">
                        {displayName}
                      </p>
                      <p className="max-w-36 truncate text-[10px] text-slate-400">
                        {roleLabel}
                      </p>
                    </div>
                    <ChevronDown size={15} className="hidden text-slate-400 sm:block" />
                  </button>

                  {profileMenuOpen && (
                    <div
                      className="absolute right-0 top-full z-40 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-2 shadow-xl"
                      role="menu"
                      aria-label="Account options"
                    >
                      <div className="border-b border-slate-100 px-3 py-2">
                        <p className="truncate text-sm font-semibold text-slate-800">
                          {displayName}
                        </p>
                        <p className="truncate text-xs text-slate-500">
                          {user?.email || user?.username || "Authenticated account"}
                        </p>
                        <p className="mt-1 truncate text-[11px] text-slate-400">
                          {organizationName} · {roleLabel}
                        </p>
                      </div>

                      {logoutError && (
                        <p className="px-3 py-2 text-xs text-rose-600" role="alert">
                          {logoutError}
                        </p>
                      )}

                      <button
                        type="button"
                        role="menuitem"
                        onClick={handleLogout}
                        disabled={isLoggingOut}
                        className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-wait disabled:opacity-60"
                      >
                        <LogOut size={16} />
                        {isLoggingOut ? "Signing out..." : "Sign out"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </header>

            <div className="mx-auto max-w-[1600px] p-5 sm:p-8">
              {/* Page heading */}
              <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
                <div>
                  <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
                    <Sparkles size={12} />
                    Demonstration overview
                  </div>
                  <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-[28px]">
                    Welcome back, {displayName.split(" ")[0]}
                  </h1>
                  <p className="mt-1 text-sm text-slate-500">
                    Your workspace shortcuts and a preview of the FIN-01 interface.
                  </p>
                </div>

                <Link
                  href="/invoices"
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800"
                >
                  <FileText size={17} />
                  Open invoice workspace
                  <ArrowRight size={15} />
                </Link>
              </div>

              {/* Sample-data notice */}
              <div className="mb-6 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
                <Activity size={15} className="mt-0.5 shrink-0" />
                <span>
                  <strong>Sample dashboard data.</strong> The figures, recent invoices
                  and activity below are static demonstration content; they are not
                  fetched from Django and do not describe {organizationName}. Use the
                  live <Link href="/invoices" className="font-semibold underline">Invoices</Link>{" "}
                  and <Link href="/accounting" className="font-semibold underline">Accounting</Link>{" "}
                  workspaces for current records.
                </span>
              </div>

              {/* Sample metric cards */}
              <section
                className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
                aria-label="Sample dashboard metrics"
              >
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
                        <span className="font-medium text-slate-600">
                          {metric.change}
                        </span>
                        <span className="text-slate-400">{metric.description}</span>
                      </div>
                    </div>
                  );
                })}
              </section>

              {/* Dashboard preview columns */}
              <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.85fr)]">
                {/* Sample invoices */}
                <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-200/30">
                  <div className="flex flex-col justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center">
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">
                        Sample recent invoices
                      </h2>
                      <p className="mt-1 text-xs text-slate-400">
                        Static preview records — not live invoice data.
                      </p>
                    </div>
                    <Link
                      href="/invoices"
                      className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:text-blue-800"
                    >
                      View live invoices <ArrowRight size={14} />
                    </Link>
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
                        placeholder="Search sample invoices..."
                        className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs outline-none focus:border-blue-400"
                        aria-label="Search sample invoices"
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
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {filteredInvoices.map((invoice) => (
                          <tr key={invoice.id} className="transition hover:bg-slate-50/70">
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
                            <td className="whitespace-nowrap px-4 py-4 text-xs font-semibold text-slate-800">
                              {invoice.amount}
                            </td>
                            <td className="px-4 py-4">
                              <StatusBadge status={invoice.status} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {filteredInvoices.length === 0 && (
                      <div className="px-5 py-12 text-center">
                        <Search className="mx-auto text-slate-300" size={25} />
                        <p className="mt-3 text-sm font-medium text-slate-600">
                          No matching sample invoices
                        </p>
                        <p className="mt-1 text-xs text-slate-400">
                          Try another search or filter.
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="border-t border-slate-100 px-5 py-3">
                    <p className="text-[10px] text-slate-400">
                      Showing {filteredInvoices.length} of {sampleInvoices.length} sample invoices
                    </p>
                  </div>
                </section>

                {/* Activity and workflow preview */}
                <div className="space-y-6">
                  <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/30">
                    <div>
                      <h2 className="text-sm font-bold text-slate-900">
                        Sample activity
                      </h2>
                      <p className="mt-1 text-xs text-slate-400">
                        Static activity examples for the interface preview.
                      </p>
                    </div>

                    <div className="mt-5 space-y-5">
                      <div className="flex gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                          <CheckCircle2 size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs leading-5 text-slate-700">
                            <strong className="font-semibold">INV-2026-039</strong> was approved.
                          </p>
                          <p className="mt-1 text-[10px] text-slate-400">24 minutes ago</p>
                        </div>
                      </div>

                      <div className="flex gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-700">
                          <Sparkles size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs leading-5 text-slate-700">
                            AI extraction completed for <strong className="font-semibold">INV-2026-041</strong>.
                          </p>
                          <p className="mt-1 text-[10px] text-slate-400">1 hour ago</p>
                        </div>
                      </div>

                      <div className="flex gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-700">
                          <FileText size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs leading-5 text-slate-700">
                            New invoice received from <strong className="font-semibold">ABC Engineering Ltd</strong>.
                          </p>
                          <p className="mt-1 text-[10px] text-slate-400">2 hours ago</p>
                        </div>
                      </div>

                      <div className="flex gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-rose-50 text-rose-700">
                          <X size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs leading-5 text-slate-700">
                            <strong className="font-semibold">INV-2026-037</strong> was returned for correction.
                          </p>
                          <p className="mt-1 text-[10px] text-slate-400">Yesterday</p>
                        </div>
                      </div>
                    </div>
                  </section>

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
                            <FileText size={14} />
                          </div>
                          <div className="h-7 w-px bg-slate-200" />
                        </div>
                        <div className="pb-4">
                          <p className="text-xs font-semibold text-slate-800">Document received</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">Invoice uploaded</p>
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
                          <p className="text-xs font-semibold text-slate-800">AI extraction and validation</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">Information captured and checked</p>
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
                          <p className="text-xs font-semibold text-slate-800">Human review</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">Corrections and verification</p>
                        </div>
                      </div>

                      <div className="flex gap-3">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                          <ShieldCheck size={14} />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-slate-800">Financial approval</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">Independent approval decision</p>
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
      </main>
    </ProtectedRoute>
  );
}
