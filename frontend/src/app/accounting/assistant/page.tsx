
"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Bot } from "lucide-react";

import { ProtectedRoute } from "@/components/protected-route";
import { useAuth } from "@/components/auth-provider";
import { FinancialAssistant } from "@/components/accounting/financial-assistant";

function FinancialAssistantWorkspace() {
  const { user } = useAuth();

  const organizations = user?.organizations ?? [];

  const [selectedOrganizationId, setSelectedOrganizationId] =
    useState("");

  const organizationId =
    selectedOrganizationId || organizations[0]?.id || "";

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
      <div className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">
        <Link
          href="/accounting"
          className="mb-5 inline-flex items-center gap-2 text-xs font-semibold text-slate-500 transition hover:text-blue-700"
        >
          <ArrowLeft size={15} />
          Back to Accounting
        </Link>

        <header className="mb-6 flex flex-col justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-700 text-white">
              <Bot size={23} />
            </div>

            <div>
              <h1 className="text-lg font-bold text-slate-900">
                FIN-01 Financial Assistant
              </h1>
              <p className="mt-1 text-xs text-slate-500">
                Your organisation&apos;s AI-powered financial reporting workspace.
              </p>
            </div>
          </div>

          <div className="w-full sm:w-64">
            <label
              htmlFor="assistant-organization"
              className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-500"
            >
              Organisation
            </label>

            <select
              id="assistant-organization"
              value={organizationId}
              onChange={(event) =>
                setSelectedOrganizationId(event.target.value)
              }
              disabled={organizations.length === 0}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-50"
            >
              {organizations.map((organization) => (
                <option key={organization.id} value={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
          </div>
        </header>

        {organizationId ? (
          <FinancialAssistant
            key={organizationId}
            organizationId={organizationId}
            layout="workspace"
          />
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-12 text-center">
            <p className="text-sm font-semibold text-slate-700">
              No organisation available
            </p>
            <p className="mt-2 text-xs text-slate-500">
              You need an active organisation membership to use the Financial Assistant.
            </p>
          </div>
        )}

        <p className="mt-5 text-center text-[10px] text-slate-400">
          FIN-01 provides read-only financial reporting. Verify important
          decisions against the underlying accounting records.
        </p>
      </div>
    </main>
  );
}

export default function FinancialAssistantPage() {
  return (
    <ProtectedRoute>
      <FinancialAssistantWorkspace />
    </ProtectedRoute>
  );
}
