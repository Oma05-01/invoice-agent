"use client";

import { useMemo, useState, type FormEvent } from "react";

import {
  AlertCircle,
  CheckCircle2,
  LoaderCircle,
  Plus,
  Trash2,
} from "lucide-react";

import { createAdjustmentJournal } from "@/lib/accounting";

import type {
  AccountingAccount,
  JournalAdjustmentLineInput,
  JournalAdjustmentRequest,
  JournalEntry,
} from "@/types/accounting";

type Props = {
  organizationId: string;
  journals: JournalEntry[];
  accounts: AccountingAccount[];
  canCreate: boolean;
  onCreated: () => void;
};

type AdjustmentFormLine = {
  id: string;
  accountId: string;
  description: string;
  debit: string;
  credit: string;
};

function createEmptyLine(): AdjustmentFormLine {
  return {
    id: `${Date.now()}-${Math.random()}`,
    accountId: "",
    description: "",
    debit: "0.00",
    credit: "0.00",
  };
}

function getLocalDate(): string {
  const now = new Date();

  const localDate = new Date(
    now.getTime() - now.getTimezoneOffset() * 60_000,
  );

  return localDate.toISOString().slice(0, 10);
}

function parseMinorUnits(value: string): number | null {
  const trimmed = value.trim();

  if (!/^\d+(?:\.\d{1,2})?$/.test(trimmed)) {
    return null;
  }

  const amount = Number(trimmed);

  if (!Number.isFinite(amount) || amount < 0) {
    return null;
  }

  return Math.round(amount * 100);
}

function formatAmount(
  valueInMinorUnits: number,
  currency: string,
): string {
  const value = valueInMinorUnits / 100;

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

function getJournalLabel(journal: JournalEntry): string {
  const reference = journal.reference || journal.id.slice(0, 8);

  return `${reference} — ${journal.entry_date} (${journal.status})`;
}

export function JournalAdjustmentForm({
  organizationId,
  journals,
  accounts,
  canCreate,
  onCreated,
}: Props) {
  const eligibleJournals = useMemo(
    () =>
      journals.filter(
        (journal) =>
          (journal.status === "posted" ||
            journal.status === "reversed") &&
          !journal.reversal_of_id,
      ),
    [journals],
  );

  const activeAccounts = useMemo(
    () => accounts.filter((account) => account.is_active),
    [accounts],
  );

  const [originalJournalId, setOriginalJournalId] = useState("");
  const [entryDate, setEntryDate] = useState(getLocalDate);
  const [reason, setReason] = useState("");
  const [description, setDescription] = useState("");

  const [lines, setLines] = useState<AdjustmentFormLine[]>([
    createEmptyLine(),
    createEmptyLine(),
  ]);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [successMessage, setSuccessMessage] = useState("");

  const effectiveOriginalJournalId = eligibleJournals.some(
    (journal) => journal.id === originalJournalId,
  )
    ? originalJournalId
    : eligibleJournals[0]?.id ?? "";

  const selectedJournal = eligibleJournals.find(
    (journal) => journal.id === effectiveOriginalJournalId,
  );

  const totals = useMemo(() => {
    return lines.reduce(
      (result, line) => {
        const debit = parseMinorUnits(line.debit);
        const credit = parseMinorUnits(line.credit);

        return {
          debit: result.debit + (debit ?? 0),
          credit: result.credit + (credit ?? 0),
        };
      },
      { debit: 0, credit: 0 },
    );
  }, [lines]);

  function updateLine(
    lineId: string,
    field: keyof Omit<AdjustmentFormLine, "id">,
    value: string,
  ) {
    setLines((current) =>
      current.map((line) =>
        line.id === lineId
          ? { ...line, [field]: value }
          : line,
      ),
    );

    setValidationErrors([]);
    setError("");
    setSuccessMessage("");
  }

  function addLine() {
    setLines((current) => [...current, createEmptyLine()]);
    setValidationErrors([]);
  }

  function removeLine(lineId: string) {
    setLines((current) =>
      current.length <= 2
        ? current
        : current.filter((line) => line.id !== lineId),
    );

    setValidationErrors([]);
  }

  function validateForm(): string[] {
    const errors: string[] = [];

    if (!effectiveOriginalJournalId || !selectedJournal) {
      errors.push("Select an eligible original journal.");
    }

    if (!entryDate) {
      errors.push("Enter the adjustment entry date.");
    }

    if (!reason.trim()) {
      errors.push("Provide a reason for this adjustment.");
    }

    if (lines.length < 2) {
      errors.push("An adjustment must contain at least two lines.");
    }

    lines.forEach((line, index) => {
      const lineNumber = index + 1;

      const debit = parseMinorUnits(line.debit);
      const credit = parseMinorUnits(line.credit);

      if (!line.accountId) {
        errors.push(`Select an account for line ${lineNumber}.`);
      }

      if (debit === null || credit === null) {
        errors.push(
          `Line ${lineNumber} must contain valid non-negative amounts with no more than two decimal places.`,
        );

        return;
      }

      if (debit > 0 && credit > 0) {
        errors.push(
          `Line ${lineNumber} cannot contain both a debit and a credit.`,
        );
      } else if (debit === 0 && credit === 0) {
        errors.push(
          `Enter a debit or credit amount for line ${lineNumber}.`,
        );
      }
    });

    if (totals.debit <= 0 || totals.credit <= 0) {
      errors.push(
        "The adjustment must have positive debit and credit totals.",
      );
    } else if (totals.debit !== totals.credit) {
      errors.push("Total debits must equal total credits.");
    }

    return errors;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canCreate || saving) {
      return;
    }

    setError("");
    setSuccessMessage("");

    const errors = validateForm();

    setValidationErrors(errors);

    if (errors.length > 0) {
      return;
    }

    const payloadLines: JournalAdjustmentLineInput[] = lines.map(
      (line) => ({
        account_id: line.accountId,
        debit: line.debit.trim(),
        credit: line.credit.trim(),
        description: line.description.trim(),
      }),
    );

    const payload: JournalAdjustmentRequest = {
      entry_date: entryDate,
      reason: reason.trim(),
      description: description.trim(),
      lines: payloadLines,
    };

    setSaving(true);

    try {
      const response = await createAdjustmentJournal(
        organizationId,
        effectiveOriginalJournalId,
        payload,
      );

      const reference =
        response.journal.reference ||
        response.journal.id.slice(0, 8);

      setSuccessMessage(
        response.message ||
          `Adjustment draft ${reference} was created successfully.`,
      );

      setReason("");
      setDescription("");
      setEntryDate(getLocalDate());
      setLines([
        createEmptyLine(),
        createEmptyLine(),
      ]);

      setValidationErrors([]);

      onCreated();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create the adjustment journal.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="border-b border-slate-100 bg-slate-50/60 p-5">
      <div className="mb-4">
        <h2 className="text-sm font-bold text-slate-900">
          Create adjustment journal
        </h2>

        <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
          Create a separate journal to correct or reclassify a posted
          transaction. The original journal remains in the audit history.
          The adjustment will be saved as a draft and must be posted
          separately by an authorized user.
        </p>
      </div>

      {successMessage && (
        <div
          role="status"
          className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"
        >
          <CheckCircle2
            size={16}
            className="mt-0.5 shrink-0"
          />

          <span>{successMessage}</span>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"
        >
          <AlertCircle
            size={16}
            className="mt-0.5 shrink-0"
          />

          <span>{error}</span>
        </div>
      )}

      {validationErrors.length > 0 && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3"
        >
          <p className="text-xs font-semibold text-amber-800">
            Please correct the following:
          </p>

          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-800">
            {validationErrors.map((message, index) => (
              <li key={`${index}-${message}`}>
                {message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {eligibleJournals.length === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-500">
          There are no posted or reversed original journals available
          for adjustment in this organization.
        </p>
      ) : activeAccounts.length < 2 ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800">
          At least two active accounts are required before an
          adjustment journal can be created.
        </p>
      ) : (
        <form
          onSubmit={handleSubmit}
          className="space-y-5"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-600">
                Original journal
              </span>

              <select
                value={effectiveOriginalJournalId}
                onChange={(event) => {
                  setOriginalJournalId(event.target.value);
                  setError("");
                  setValidationErrors([]);
                  setSuccessMessage("");
                }}
                required
                disabled={saving || !canCreate}
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-100"
              >
                {eligibleJournals.map((journal) => (
                  <option
                    key={journal.id}
                    value={journal.id}
                  >
                    {getJournalLabel(journal)}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-600">
                Adjustment entry date
              </span>

              <input
                type="date"
                value={entryDate}
                onChange={(event) =>
                  setEntryDate(event.target.value)
                }
                required
                disabled={saving || !canCreate}
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-100"
              />
            </label>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-600">
              Reason for adjustment
            </span>

            <textarea
              value={reason}
              onChange={(event) =>
                setReason(event.target.value)
              }
              required
              rows={2}
              maxLength={2000}
              placeholder="Explain why this adjustment is required..."
              disabled={saving || !canCreate}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-100"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-600">
              Journal description

              <span className="ml-1 font-normal text-slate-400">
                (optional)
              </span>
            </span>

            <input
              value={description}
              onChange={(event) =>
                setDescription(event.target.value)
              }
              maxLength={255}
              placeholder="Brief description of the adjustment"
              disabled={saving || !canCreate}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-100"
            />
          </label>

          <div>
            <div className="mb-3 flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
              <div>
                <h3 className="text-xs font-bold text-slate-800">
                  Adjustment lines
                </h3>

                <p className="mt-1 text-[11px] text-slate-400">
                  Each line must contain either a debit or a credit.
                </p>
              </div>

              <button
                type="button"
                onClick={addLine}
                disabled={saving || !canCreate}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Plus size={14} />
                Add line
              </button>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full min-w-[850px] text-left">
                <thead>
                  <tr className="bg-slate-100">
                    <th className="w-10 px-3 py-3 text-[11px] font-semibold text-slate-500">
                      #
                    </th>

                    <th className="px-3 py-3 text-[11px] font-semibold text-slate-500">
                      Account
                    </th>

                    <th className="px-3 py-3 text-[11px] font-semibold text-slate-500">
                      Description
                    </th>

                    <th className="w-36 px-3 py-3 text-right text-[11px] font-semibold text-slate-500">
                      Debit
                    </th>

                    <th className="w-36 px-3 py-3 text-right text-[11px] font-semibold text-slate-500">
                      Credit
                    </th>

                    <th className="w-14 px-3 py-3" />
                  </tr>
                </thead>

                <tbody className="divide-y divide-slate-100">
                  {lines.map((line, index) => (
                    <tr key={line.id}>
                      <td className="px-3 py-3 text-xs text-slate-400">
                        {index + 1}
                      </td>

                      <td className="min-w-[190px] px-3 py-3">
                        <select
                          value={line.accountId}
                          onChange={(event) =>
                            updateLine(
                              line.id,
                              "accountId",
                              event.target.value,
                            )
                          }
                          required
                          disabled={saving || !canCreate}
                          aria-label={`Account for adjustment line ${index + 1}`}
                          className="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-blue-500 disabled:bg-slate-100"
                        >
                          <option value="">
                            Select account
                          </option>

                          {activeAccounts.map((account) => (
                            <option
                              key={account.id}
                              value={account.id}
                            >
                              {account.code} — {account.name}
                            </option>
                          ))}
                        </select>
                      </td>

                      <td className="min-w-[180px] px-3 py-3">
                        <input
                          value={line.description}
                          onChange={(event) =>
                            updateLine(
                              line.id,
                              "description",
                              event.target.value,
                            )
                          }
                          maxLength={255}
                          disabled={saving || !canCreate}
                          aria-label={`Description for adjustment line ${index + 1}`}
                          placeholder="Line description"
                          className="h-9 w-full rounded-md border border-slate-200 px-2 text-xs outline-none focus:border-blue-500 disabled:bg-slate-100"
                        />
                      </td>

                      <td className="px-3 py-3">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={line.debit}
                          onChange={(event) =>
                            updateLine(
                              line.id,
                              "debit",
                              event.target.value,
                            )
                          }
                          disabled={saving || !canCreate}
                          aria-label={`Debit for adjustment line ${index + 1}`}
                          className="h-9 w-full rounded-md border border-slate-200 px-2 text-right text-xs outline-none focus:border-blue-500 disabled:bg-slate-100"
                        />
                      </td>

                      <td className="px-3 py-3">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={line.credit}
                          onChange={(event) =>
                            updateLine(
                              line.id,
                              "credit",
                              event.target.value,
                            )
                          }
                          disabled={saving || !canCreate}
                          aria-label={`Credit for adjustment line ${index + 1}`}
                          className="h-9 w-full rounded-md border border-slate-200 px-2 text-right text-xs outline-none focus:border-blue-500 disabled:bg-slate-100"
                        />
                      </td>

                      <td className="px-3 py-3 text-center">
                        <button
                          type="button"
                          onClick={() => removeLine(line.id)}
                          disabled={
                            saving ||
                            lines.length <= 2 ||
                            !canCreate
                          }
                          aria-label={`Remove adjustment line ${index + 1}`}
                          className="rounded-md p-2 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Total debit
                </p>

                <p className="mt-1 text-sm font-bold tabular-nums text-slate-800">
                  {formatAmount(
                    totals.debit,
                    selectedJournal?.currency || "NGN",
                  )}
                </p>
              </div>

              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Total credit
                </p>

                <p className="mt-1 text-sm font-bold tabular-nums text-slate-800">
                  {formatAmount(
                    totals.credit,
                    selectedJournal?.currency || "NGN",
                  )}
                </p>
              </div>
            </div>

            <button
              type="submit"
              disabled={
                saving ||
                !canCreate ||
                !selectedJournal ||
                activeAccounts.length < 2
              }
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 text-xs font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? (
                <>
                  <LoaderCircle
                    size={15}
                    className="animate-spin"
                  />
                  Creating draft...
                </>
              ) : (
                "Create adjustment draft"
              )}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
