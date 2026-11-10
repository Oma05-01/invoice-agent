"use client";

import { Fragment, useState, type FormEvent } from "react";

import {
  AlertCircle,
  CheckCircle2,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  Save,
  ShieldCheck,
} from "lucide-react";

import {
  postJournalEntry,
  reverseJournalEntry,
  updateJournalLine,
  updateDraftJournalEntryDate,
} from "@/lib/accounting";

import type {
  AccountingAccount,
  JournalEntry,
  JournalLine,
  JournalLineCorrections,
} from "@/types/accounting";


type Props = {
  organizationId: string;
  journal: JournalEntry;
  accounts: AccountingAccount[];
  canEditDraft: boolean;
  canPostOrReverse: boolean;
  reversalJournal?: JournalEntry;
  onChanged: () => void;
};


type PendingAction = "post" | "reverse" | null;


function formatAmount(value: number, currency: string) {
  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency: currency || "NGN",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}


function toMinorUnits(value: string): number {
  return Math.round(Number(value) * 100);
}


function getTotals(lines: JournalLine[]) {
  return lines.reduce(
    (totals, line) => ({
      debit: totals.debit + toMinorUnits(line.debit),
      credit: totals.credit + toMinorUnits(line.credit),
    }),
    { debit: 0, credit: 0 },
  );
}


function JournalLineEditor({
  organizationId,
  journal,
  line,
  accounts,
  canEdit,
  onSaved,
}: {
  organizationId: string;
  journal: JournalEntry;
  line: JournalLine;
  accounts: AccountingAccount[];
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [accountId, setAccountId] = useState(line.account?.id ?? "");
  const [description, setDescription] = useState(line.description);
  const [debit, setDebit] = useState(line.debit);
  const [credit, setCredit] = useState(line.credit);
  const [correctionReason, setCorrectionReason] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const changed =
    accountId !== (line.account?.id ?? "") ||
    description !== line.description ||
    debit !== line.debit ||
    credit !== line.credit;

  const selectableAccounts = accounts.filter(
    (account) =>
      account.is_active || account.id === line.account?.id,
  );

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!changed || !correctionReason.trim()) return;

    setSaving(true);
    setError("");
    setSuccess(false);

    const corrections: JournalLineCorrections = {
      account_id: accountId || null,
      description,
      debit,
      credit,
      correction_reason: correctionReason.trim(),
    };

    try {
      await updateJournalLine(
        organizationId,
        journal.id,
        line.id,
        corrections,
      );

      setSuccess(true);
      setCorrectionReason("");
      onSaved();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save the journal-line correction.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Fragment>
      <tr className="align-top">
        <td className="px-4 py-3 text-xs text-slate-500">
          {line.line_number}
        </td>

        <td className="min-w-[190px] px-4 py-3">
          {canEdit ? (
            <select
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-blue-500"
              aria-label={`Account for journal line ${line.line_number}`}
            >
              <option value="">Select account</option>

              {selectableAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.code} — {account.name}
                  {!account.is_active ? " (Inactive)" : ""}
                </option>
              ))}
            </select>
          ) : line.account ? (
            <>
              <p className="text-xs font-semibold text-slate-800">
                {line.account.code}
              </p>
              <p className="mt-0.5 text-xs text-slate-500">
                {line.account.name}
              </p>
            </>
          ) : (
            <span className="text-xs font-medium text-amber-700">
              Account not assigned
            </span>
          )}
        </td>

        <td className="min-w-[180px] px-4 py-3">
          {canEdit ? (
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="h-9 w-full rounded-lg border border-slate-200 px-2 text-xs outline-none focus:border-blue-500"
              aria-label={`Description for journal line ${line.line_number}`}
            />
          ) : (
            <span className="text-xs text-slate-600">
              {line.description || "—"}
            </span>
          )}
        </td>

        <td className="min-w-[135px] px-4 py-3">
          {canEdit ? (
            <input
              type="number"
              min="0"
              step="0.01"
              value={debit}
              onChange={(event) => setDebit(event.target.value)}
              className="h-9 w-full rounded-lg border border-slate-200 px-2 text-right text-xs outline-none focus:border-blue-500"
              aria-label={`Debit for journal line ${line.line_number}`}
            />
          ) : (
            <span className="whitespace-nowrap text-xs text-slate-700">
              {formatAmount(Number(line.debit), journal.currency)}
            </span>
          )}
        </td>

        <td className="min-w-[135px] px-4 py-3">
          {canEdit ? (
            <input
              type="number"
              min="0"
              step="0.01"
              value={credit}
              onChange={(event) => setCredit(event.target.value)}
              className="h-9 w-full rounded-lg border border-slate-200 px-2 text-right text-xs outline-none focus:border-blue-500"
              aria-label={`Credit for journal line ${line.line_number}`}
            />
          ) : (
            <span className="whitespace-nowrap text-xs text-slate-700">
              {formatAmount(Number(line.credit), journal.currency)}
            </span>
          )}
        </td>

        {canEdit && (
          <td className="min-w-[210px] px-4 py-3">
            <form onSubmit={handleSave} className="space-y-2">
              <input
                value={correctionReason}
                onChange={(event) =>
                  setCorrectionReason(event.target.value)
                }
                placeholder="Reason for correction"
                className="h-9 w-full rounded-lg border border-slate-200 px-2 text-xs outline-none focus:border-blue-500"
                required
                aria-label={`Correction reason for journal line ${line.line_number}`}
              />

              <button
                type="submit"
                disabled={
                  saving ||
                  !changed ||
                  !correctionReason.trim()
                }
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving ? (
                  <LoaderCircle size={13} className="animate-spin" />
                ) : (
                  <Save size={13} />
                )}
                Save correction
              </button>
            </form>
          </td>
        )}
      </tr>

      {(error || success) && (
        <tr>
          <td
            colSpan={canEdit ? 6 : 5}
            className="px-4 pb-3 pt-0"
          >
            {error && (
              <p role="alert" className="text-xs text-rose-700">
                {error}
              </p>
            )}

            {success && !error && (
              <p className="inline-flex items-center gap-1.5 text-xs text-emerald-700">
                <CheckCircle2 size={13} />
                Correction saved.
              </p>
            )}
          </td>
        </tr>
      )}
    </Fragment>
  );
}


export function JournalDetailPanel({
  organizationId,
  journal,
  accounts,
  canEditDraft,
  canPostOrReverse,
  reversalJournal,
  onChanged,
}: Props) {
  const [pendingAction, setPendingAction] =
    useState<PendingAction>(null);

  const [reversalReason, setReversalReason] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [entryDate, setEntryDate] = useState(journal.entry_date);
  const [dateCorrectionReason, setDateCorrectionReason] = useState("");
  const [dateSaving, setDateSaving] = useState(false);
  const [dateError, setDateError] = useState("");
  const [dateSuccess, setDateSuccess] = useState(false);

  const totals = getTotals(journal.lines);

  const balanced =
    totals.debit > 0 && totals.debit === totals.credit;

  const canEdit =
    journal.status === "draft" && canEditDraft;

  async function handleConfirmAction() {
    if (!pendingAction) return;

    if (
      pendingAction === "reverse" &&
      !reversalReason.trim()
    ) {
      setActionError("A reversal reason is required.");
      return;
    }

    setActionLoading(true);
    setActionError("");

    try {
      if (pendingAction === "post") {
        await postJournalEntry(
          organizationId,
          journal.id,
        );
      } else {
        await reverseJournalEntry(
          organizationId,
          journal.id,
          {
            reversal_reason: reversalReason.trim(),
          },
        );
      }

      setPendingAction(null);
      setReversalReason("");
      onChanged();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "The accounting operation could not be completed.",
      );
    } finally {
      setActionLoading(false);
    }
  }

    async function handleDateUpdate(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!canEdit || dateSaving) return;

    if (!entryDate || !dateCorrectionReason.trim()) {
      setDateError(
        "An entry date and correction reason are required.",
      );
      return;
    }

    setDateSaving(true);
    setDateError("");
    setDateSuccess(false);

    try {
      const updated = await updateDraftJournalEntryDate(
        organizationId,
        journal.id,
        {
          entry_date: entryDate,
          correction_reason: dateCorrectionReason.trim(),
        },
      );

      setEntryDate(updated.entry_date);
      setDateCorrectionReason("");
      setDateSuccess(true);

      onChanged();
    } catch (err) {
      setDateError(
        err instanceof Error
          ? err.message
          : "Unable to update the journal entry date.",
      );
    } finally {
      setDateSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <h3 className="text-sm font-bold text-slate-800">
            Journal details
          </h3>

          <p className="mt-1 text-xs text-slate-500">
            {journal.description || "No journal description."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canEdit && (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
              <LockKeyhole size={13} />
              Draft — editable
            </span>
          )}

          {journal.status === "draft" && canPostOrReverse && (
            <button
              type="button"
              onClick={() => {
                setActionError("");
                setPendingAction("post");
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-800"
            >
              <ShieldCheck size={14} />
              Post journal
            </button>
          )}

          {journal.status === "posted" && canPostOrReverse && (
            <button
              type="button"
              onClick={() => {
                setActionError("");
                setReversalReason("");
                setPendingAction("reverse");
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50"
            >
              <RotateCcw size={14} />
              Reverse journal
            </button>
          )}
        </div>
      </div>

            {canEdit && (
        <form
          onSubmit={handleDateUpdate}
          className="rounded-lg border border-slate-200 bg-white p-4"
        >
          <h4 className="text-xs font-bold text-slate-800">
            Draft journal date
          </h4>

          <p className="mt-1 text-xs text-slate-500">
            Changes to the entry date are recorded in the journal audit history.
          </p>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-600">
                Entry date
              </span>

              <input
                type="date"
                value={entryDate}
                onChange={(event) => {
                  setEntryDate(event.target.value);
                  setDateError("");
                  setDateSuccess(false);
                }}
                required
                disabled={dateSaving}
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs outline-none focus:border-blue-500 disabled:bg-slate-100"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-600">
                Reason for date correction
              </span>

              <input
                value={dateCorrectionReason}
                onChange={(event) => {
                  setDateCorrectionReason(event.target.value);
                  setDateError("");
                }}
                required
                maxLength={2000}
                placeholder="Explain why the date is changing"
                disabled={dateSaving}
                className="h-10 w-full rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-500 disabled:bg-slate-100"
              />
            </label>
          </div>

          {dateError && (
            <p role="alert" className="mt-3 text-xs text-rose-700">
              {dateError}
            </p>
          )}

          {dateSuccess && (
            <p className="mt-3 inline-flex items-center gap-1.5 text-xs text-emerald-700">
              <CheckCircle2 size={13} />
              Journal date updated and recorded in the audit history.
            </p>
          )}

          <button
            type="submit"
            disabled={
              dateSaving ||
              !dateCorrectionReason.trim() ||
              !entryDate
            }
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {dateSaving ? (
              <LoaderCircle size={13} className="animate-spin" />
            ) : (
              <Save size={13} />
            )}
            Save date correction
          </button>
        </form>
      )}

      {journal.source_invoice_id && (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="text-xs text-slate-500">
            Source invoice ID
          </p>
          <p className="mt-1 break-all font-mono text-xs font-semibold text-slate-800">
            {journal.source_invoice_id}
          </p>
        </div>
      )}

      {journal.reversal_of_id && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          This is a reversal of journal{" "}
          <span className="font-mono font-semibold">
            {journal.reversal_of_id}
          </span>.
        </div>
      )}

      {reversalJournal && journal.status === "reversed" && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3">
          <p className="text-xs font-semibold text-rose-800">
            This journal has been reversed.
          </p>
          <p className="mt-1 text-xs text-rose-700">
            Reversal entry:{" "}
            <span className="font-mono font-semibold">
              {reversalJournal.reference || reversalJournal.id}
            </span>
          </p>
          {reversalJournal.reversal_reason && (
            <p className="mt-1 text-xs text-rose-700">
              Reason: {reversalJournal.reversal_reason}
            </p>
          )}
        </div>
      )}

      {journal.status === "draft" && !canPostOrReverse && (
        <p className="text-xs text-slate-500">
          An organization owner or finance administrator must post this journal.
        </p>
      )}

      {journal.status === "posted" && !canPostOrReverse && (
        <p className="text-xs text-slate-500">
          This journal is posted and cannot be edited. An owner or finance
          administrator can initiate a reversal when necessary.
        </p>
      )}

      {journal.status === "draft" && !canEditDraft && (
        <p className="text-xs text-slate-500">
          Your organization role does not permit draft journal corrections.
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] text-left">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50">
              <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                Line
              </th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                Account
              </th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                Description
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500">
                Debit
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500">
                Credit
              </th>
              {canEdit && (
                <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                  Correction
                </th>
              )}
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100">
            {journal.lines.map((line) => (
              <JournalLineEditor
                 key={JSON.stringify([
                    line.id,
                    line.account?.id ?? null,
                    line.description,
                    line.debit,
                    line.credit,
                ])}
                organizationId={organizationId}
                journal={journal}
                line={line}
                accounts={accounts}
                canEdit={canEdit}
                onSaved={onChanged}
              />
            ))}
          </tbody>

          <tfoot>
            <tr className="border-t border-slate-200 bg-slate-50">
              <td
                colSpan={3}
                className="px-4 py-3 text-xs font-bold text-slate-700"
              >
                Journal totals
              </td>

              <td className="px-4 py-3 text-right text-xs font-bold text-slate-900">
                {formatAmount(
                  totals.debit / 100,
                  journal.currency,
                )}
              </td>

              <td className="px-4 py-3 text-right text-xs font-bold text-slate-900">
                {formatAmount(
                  totals.credit / 100,
                  journal.currency,
                )}
              </td>

              {canEdit && <td />}
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs">
          {balanced ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-700">
              <CheckCircle2 size={14} />
              Debits and credits are balanced.
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-rose-700">
              <AlertCircle size={14} />
              Debits and credits are not balanced.
            </span>
          )}
        </div>

        {journal.status === "draft" && canPostOrReverse && (
          <p className="text-xs text-slate-500">
            Posting is validated by the accounting service.
          </p>
        )}
      </div>

      {pendingAction && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !actionLoading) {
              setPendingAction(null);
              setActionError("");
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="journal-action-title"
            className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3
                  id="journal-action-title"
                  className="text-lg font-bold text-slate-900"
                >
                  {pendingAction === "post"
                    ? "Post journal entry?"
                    : "Reverse journal entry?"}
                </h3>

                <p className="mt-2 text-sm leading-6 text-slate-500">
                  {pendingAction === "post"
                    ? "Posting makes this journal immutable and includes it in posted accounting records. Confirm that the account classifications and amounts have been reviewed."
                    : "A reversal creates a new posted journal with the opposite debit and credit entries. The original journal remains in the accounting history."}
                </p>
              </div>
            </div>

            {pendingAction === "reverse" && (
              <div className="mt-5">
                <label
                  htmlFor="reversal-reason"
                  className="mb-2 block text-xs font-semibold text-slate-700"
                >
                  Reversal reason
                </label>

                <textarea
                  id="reversal-reason"
                  rows={3}
                  value={reversalReason}
                  onChange={(event) =>
                    setReversalReason(event.target.value)
                  }
                  placeholder="Explain why this journal must be reversed..."
                  className="w-full rounded-lg border border-slate-200 p-3 text-sm outline-none focus:border-blue-500"
                />
              </div>
            )}

            {actionError && (
              <p role="alert" className="mt-3 text-sm text-rose-700">
                {actionError}
              </p>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                disabled={actionLoading}
                onClick={() => {
                  setPendingAction(null);
                  setActionError("");
                }}
                className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>

              <button
                type="button"
                disabled={
                  actionLoading ||
                  (pendingAction === "reverse" &&
                    !reversalReason.trim())
                }
                onClick={handleConfirmAction}
                className={`inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                  pendingAction === "post"
                    ? "bg-emerald-700 hover:bg-emerald-800"
                    : "bg-rose-700 hover:bg-rose-800"
                }`}
              >
                {actionLoading && (
                  <LoaderCircle size={15} className="animate-spin" />
                )}

                {pendingAction === "post"
                  ? "Confirm posting"
                  : "Confirm reversal"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}