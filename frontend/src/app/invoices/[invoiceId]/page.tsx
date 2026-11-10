
"use client";

import {
  useEffect,
  useState,
  type FormEvent,
} from "react";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { ProtectedRoute } from "@/components/protected-route";

import {
  fetchInvoiceReview,
  getInvoiceDocumentPreviewUrl,
  fetchVendors,
   createVendor,
  assignInvoiceVendor,
  updateInvoiceHeader,
  type Vendor,
  type InvoiceHeaderCorrections,
  addInvoiceLineItem,
  updateInvoiceLineItem,
  deleteInvoiceLineItem,
  type InvoiceLineItemCorrections,
  submitInvoiceForApproval,
  InvoiceSubmissionError,
} from "@/lib/invoices";

type DataRecord = Record<string, unknown>;

type InvoiceReview = Awaited<
  ReturnType<typeof fetchInvoiceReview>
>;

function asRecord(value: unknown): DataRecord {
  if (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  ) {
    return value as DataRecord;
  }

  return {};
}

function formatKey(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

const AUDIT_FIELD_LABELS: Record<string, string> = {
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  due_date: "Due date",
  currency: "Currency",
  subtotal: "Subtotal",
  tax_amount: "Tax amount",
  other_charges: "Other charges",
  total_amount: "Total amount",
  amount_due: "Amount due",
  description: "Invoice description",
  quantity: "Quantity",
  unit_price: "Unit price",
  tax_rate: "Tax rate",
  line_total: "Line total",
  ledger_code: "Ledger code",
  suggested_category: "Suggested category",
};

function getAuditFieldLabel(field: string): string {
  return AUDIT_FIELD_LABELS[field] ?? formatKey(field);
}

function describeAuditEvent(event: DataRecord): {
  title: string;
  details: string[];
  correctionReason: string;
} {
  const metadata = asRecord(event.metadata);
  const changes = asRecord(event.changes);

  const action =
    typeof event.action === "string" ? event.action : "";

  const operation =
    typeof metadata.operation === "string"
      ? metadata.operation
      : "";

  const correctionReason =
    typeof metadata.correction_reason === "string"
      ? metadata.correction_reason
      : "";

  const changedFields = [
    ...new Set(
      Object.keys(changes).flatMap((key) => {
        const parts = key.split(".");

        if (parts[0] === "line_items") {
          return parts.length >= 3
            ? [parts[parts.length - 1]]
            : [];
        }

        return key === "vendor" ? [] : [key];
      }),
    ),
  ];

  const fieldLabels = changedFields.map(getAuditFieldLabel);

  const getLineItemDescription = (
    snapshotSide: "before" | "after",
  ) => {
    for (const rawChange of Object.values(changes)) {
      const change = asRecord(rawChange);
      const snapshot = asRecord(change[snapshotSide]);

      if (
        typeof snapshot.description === "string" &&
        snapshot.description.trim()
      ) {
        return snapshot.description;
      }
    }

    return "";
  };

  if (operation === "line_item_added") {
    const description = getLineItemDescription("after");

    return {
      title: "Line item added",
      details: description ? [`Item: ${description}`] : [],
      correctionReason,
    };
  }

  if (operation === "line_item_deleted") {
    const description = getLineItemDescription("before");

    return {
      title: "Line item deleted",
      details: description ? [`Removed item: ${description}`] : [],
      correctionReason,
    };
  }

  if (operation === "line_item_updated") {
    return {
      title:
        fieldLabels.length === 1
          ? `Line item ${fieldLabels[0].toLowerCase()} updated`
          : "Line item updated",
      details: fieldLabels.length
        ? [`Updated fields: ${fieldLabels.join(", ")}`]
        : [],
      correctionReason,
    };
  }

  if (action === "field_updated") {
    return {
      title:
        fieldLabels.length === 1
          ? `${fieldLabels[0]} updated`
          : "Invoice details updated",
      details:
        fieldLabels.length > 1
          ? [`Updated fields: ${fieldLabels.join(", ")}`]
          : [],
      correctionReason,
    };
  }

  if (action === "vendor_assigned") {
    const vendorChange = asRecord(changes.vendor);
    const vendor = asRecord(vendorChange.after);
    const vendorName =
      typeof vendor.legal_name === "string"
        ? vendor.legal_name
        : "Vendor";

    return {
      title: `${vendorName} assigned`,
      details: [],
      correctionReason,
    };
  }

  const actionTitles: Record<string, string> = {
    processing_queued: "Processing queued",
    review_started: "Review started",
    validation_issue_resolved: "Validation issue resolved",
    validation_issue_ignored: "Validation issue ignored",
    review_submitted: "Review submitted",
    approval_requested: "Approval requested",
    approval_granted: "Invoice approved",
    approval_rejected: "Invoice rejected",
    reopened_for_review: "Returned for review",
  };

  return {
    title: actionTitles[action] ?? formatKey(action || "Activity"),
    details: [],
    correctionReason,
  };
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }

  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }

  return String(value);
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not provided";
  }

  return formatValue(value);
}

function formatMoney(
  value: unknown,
  currency: string = "NGN",
): string {
  if (value === null || value === undefined || value === "") {
    return "Not provided";
  }

  const amount = Number(value);

  if (!Number.isFinite(amount)) {
    return formatValue(value);
  }

  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-NG", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
}

/* -------------------------------------------------------------------------- */
/* Review field                                                               */
/* -------------------------------------------------------------------------- */

function ReviewField({
  label,
  value,
  fieldName,
  currency,
  money = false,
  confidence,
  evidence,
}: {
  label: string;
  value: unknown;
  fieldName: string;
  currency?: string;
  money?: boolean;
  confidence?: unknown;
  evidence?: unknown;
}) {
  const hasValue =
    value !== null &&
    value !== undefined &&
    value !== "";

  const score = Number(confidence);

  const hasConfidence =
    hasValue &&
    confidence !== null &&
    confidence !== undefined &&
    Number.isFinite(score);

  const evidenceItems = Array.isArray(evidence)
    ? evidence.map(asRecord)
    : [];

  return (
    <div
      data-field-name={fieldName}
      className="rounded-lg border border-gray-200 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <dt className="text-xs font-medium text-gray-500">
          {label}
        </dt>

        {hasConfidence && (
          <span className="text-xs text-gray-500">
            Model score: {Math.round(score * 100)}%
          </span>
        )}
      </div>

      <dd className="mt-1 break-words text-sm font-medium text-gray-900">
        {money
          ? formatMoney(value, currency)
          : displayValue(value)}
      </dd>

      {evidenceItems.length > 0 && (
        <details className="mt-3 border-t border-gray-100 pt-2">
          <summary className="cursor-pointer text-xs font-medium text-blue-600">
            View source evidence ({evidenceItems.length})
          </summary>

          <div className="mt-2 space-y-2">
            {evidenceItems.map((item, index) => (
              <blockquote
                key={index}
                className="rounded-md bg-gray-50 p-2 text-xs text-gray-600"
              >
                <p className="whitespace-pre-wrap">
                  {`"${displayValue(item.quote)}"`}
                </p>

                <p className="mt-1 text-gray-400">
                  Page {displayValue(item.page)}
                </p>
              </blockquote>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Line items                                                                 */
/* -------------------------------------------------------------------------- */

type LineItemDraft = {
  description: string;
  quantity: string;
  unit_price: string;
  tax_rate: string;
  line_total: string;
  ledger_code: string;
  correction_reason: string;
};

const EMPTY_LINE_ITEM_DRAFT: LineItemDraft = {
  description: "",
  quantity: "",
  unit_price: "",
  tax_rate: "",
  line_total: "",
  ledger_code: "",
  correction_reason: "",
};

function LineItemsSection({
  items,
  currency,
  organizationId,
  invoiceId,
  status,
  onUpdated,
}: {
  items: unknown[];
  currency: string;
  organizationId: string;
  invoiceId: string;
  status: string;
  onUpdated: () => Promise<void>;
}) {
  const [activeForm, setActiveForm] = useState<string | null>(null);
  const [draft, setDraft] = useState<LineItemDraft>({
    ...EMPTY_LINE_ITEM_DRAFT,
  });

  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(
    null,
  );
  const [deleteReason, setDeleteReason] = useState("");

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const canEdit = status === "needs_review";

  function updateDraft(
    field: keyof LineItemDraft,
    value: string,
  ) {
    setDraft((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function startAdding() {
    setError(null);
    setSuccess(null);
    setDeleteTargetId(null);
    setActiveForm("new");
    setDraft({ ...EMPTY_LINE_ITEM_DRAFT });
  }

  function startEditing(item: DataRecord) {
    if (typeof item.id !== "string") {
      return;
    }

    const taxRate = item.tax_rate_percent ?? item.tax_rate;

    setError(null);
    setSuccess(null);
    setDeleteTargetId(null);
    setActiveForm(item.id);

    setDraft({
      description:
        item.description == null ? "" : String(item.description),
      quantity:
        item.quantity == null ? "" : String(item.quantity),
      unit_price:
        item.unit_price == null ? "" : String(item.unit_price),
      tax_rate: taxRate == null ? "" : String(taxRate),
      line_total:
        item.line_total == null ? "" : String(item.line_total),
      ledger_code:
        item.ledger_code == null ? "" : String(item.ledger_code),
      correction_reason: "",
    });
  }

  function cancelEditing() {
    setActiveForm(null);
    setDraft({ ...EMPTY_LINE_ITEM_DRAFT });
    setError(null);
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canEdit || saving || deleting) {
      return;
    }

    const description = draft.description.trim();
    const correctionReason = draft.correction_reason.trim();

    if (!description) {
      setError("A line-item description is required.");
      return;
    }

    if (!correctionReason) {
      setError("Please provide a correction reason.");
      return;
    }

    const corrections: InvoiceLineItemCorrections = {
      description,
      quantity: draft.quantity.trim() || null,
      unit_price: draft.unit_price.trim() || null,
      tax_rate: draft.tax_rate.trim() || null,
      line_total: draft.line_total.trim() || null,
      ledger_code: draft.ledger_code.trim(),
      correction_reason: correctionReason,
    };

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      if (activeForm === "new") {
        await addInvoiceLineItem(
          organizationId,
          invoiceId,
          {
            ...corrections,
            description,
          },
        );
      } else if (activeForm) {
        await updateInvoiceLineItem(
          organizationId,
          invoiceId,
          activeForm,
          corrections,
        );
      } else {
        return;
      }

      setActiveForm(null);
      setDraft({ ...EMPTY_LINE_ITEM_DRAFT });

      try {
        await onUpdated();
        setSuccess(
          activeForm === "new"
            ? "Line item added successfully."
            : "Line item updated successfully.",
        );
      } catch {
        setError(
          "The line-item change was saved, but the review could not be refreshed. Reload the page to see the latest data.",
        );
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save the line item.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(lineItemId: string) {
    const reason = deleteReason.trim();

    if (!reason) {
      setError("Please provide a reason for deleting this line item.");
      return;
    }

    if (!canEdit || saving || deleting) {
      return;
    }

    setDeleting(true);
    setError(null);
    setSuccess(null);

    try {
      await deleteInvoiceLineItem(
        organizationId,
        invoiceId,
        lineItemId,
        reason,
      );

      setDeleteTargetId(null);
      setDeleteReason("");

      try {
        await onUpdated();
        setSuccess("Line item deleted successfully.");
      } catch {
        setError(
          "The line item was deleted, but the review could not be refreshed. Reload the page to see the latest data.",
        );
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete the line item.",
      );
    } finally {
      setDeleting(false);
    }
  }

  function renderField(
    label: string,
    field: keyof LineItemDraft,
    type: "text" | "number" = "text",
    step?: string,
  ) {
    return (
      <label key={field} className="block">
        <span className="mb-1 block text-xs font-medium text-gray-600">
          {label}
        </span>

        <input
          type={type}
          step={step}
          value={draft[field]}
          onChange={(event) =>
            updateDraft(field, event.target.value)
          }
          required={field === "description"}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      </label>
    );
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            Line items
          </h2>

          <p className="mt-1 text-xs text-gray-500">
            Review and correct the individual items extracted from the invoice.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {items.length} item(s)
          </span>

          <button
            type="button"
            onClick={startAdding}
            disabled={!canEdit || saving || deleting || activeForm !== null}
            className="rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add line item
          </button>
        </div>
      </div>

      {!canEdit && (
        <p className="mb-4 rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
          Line-item changes are only available while the invoice is awaiting review.
        </p>
      )}

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {success && (
        <div
          role="status"
          className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700"
        >
          {success}
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-sm text-gray-500">
          No line items were extracted.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="py-3 pr-4">Description</th>
                <th className="px-3 py-3 text-right">Quantity</th>
                <th className="px-3 py-3 text-right">Unit price</th>
                <th className="px-3 py-3 text-right">Tax rate</th>
                <th className="px-3 py-3 text-right">Total</th>
                <th className="px-3 py-3">Ledger code</th>
                <th className="py-3 pl-3 text-right">Actions</th>
              </tr>
            </thead>

            <tbody>
              {items.map((rawItem, index) => {
                const item = asRecord(rawItem);
                const itemId =
                  typeof item.id === "string" ? item.id : "";

                const taxRate =
                  item.tax_rate_percent ?? item.tax_rate;

                return (
                  <tr
                    key={itemId || index}
                    className="border-b border-gray-100 last:border-0"
                  >
                    <td className="py-3 pr-4 font-medium text-gray-900">
                      {displayValue(item.description)}
                    </td>

                    <td className="px-3 py-3 text-right text-gray-600">
                      {displayValue(item.quantity)}
                    </td>

                    <td className="px-3 py-3 text-right text-gray-600">
                      {formatMoney(item.unit_price, currency)}
                    </td>

                    <td className="px-3 py-3 text-right text-gray-600">
                      {taxRate == null
                        ? "Not specified"
                        : `${formatValue(taxRate)}%`}
                    </td>

                    <td className="px-3 py-3 text-right font-medium text-gray-900">
                      {formatMoney(item.line_total, currency)}
                    </td>

                    <td className="px-3 py-3 text-gray-600">
                      {displayValue(item.ledger_code)}
                    </td>

                    <td className="py-3 pl-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => startEditing(item)}
                          disabled={
                            !canEdit ||
                            !itemId ||
                            saving ||
                            deleting ||
                            activeForm !== null
                          }
                          title={
                            itemId
                              ? "Edit line item"
                              : "This item has no stored line-item ID"
                          }
                          className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          Edit
                        </button>

                        <button
                          type="button"
                          onClick={() => {
                            setError(null);
                            setSuccess(null);
                            setActiveForm(null);
                            setDeleteTargetId(itemId);
                            setDeleteReason("");
                          }}
                          disabled={
                            !canEdit ||
                            !itemId ||
                            saving ||
                            deleting ||
                            activeForm !== null
                          }
                          title={
                            itemId
                              ? "Delete line item"
                              : "This item has no stored line-item ID"
                          }
                          className="rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {activeForm !== null && (
        <form
          onSubmit={handleSave}
          className="mt-5 rounded-lg border border-blue-100 bg-blue-50/40 p-4"
        >
          <h3 className="mb-4 text-sm font-semibold text-gray-900">
            {activeForm === "new"
              ? "Add line item"
              : "Edit line item"}
          </h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {renderField("Description", "description")}
            {renderField("Quantity", "quantity", "number", "0.0001")}
            {renderField("Unit price", "unit_price", "number", "0.01")}
            {renderField("Tax rate (%)", "tax_rate", "number", "0.0001")}
            {renderField("Line total", "line_total", "number", "0.01")}
            {renderField("Ledger code", "ledger_code")}
          </div>

          <label className="mt-4 block">
            <span className="mb-1 block text-xs font-medium text-gray-600">
              Reason for correction
            </span>

            <textarea
              value={draft.correction_reason}
              onChange={(event) =>
                updateDraft("correction_reason", event.target.value)
              }
              required
              rows={2}
              maxLength={1000}
              placeholder="Explain why this line item is being added or changed."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </label>

          <p className="mt-2 text-xs text-gray-500">
            Blank numeric fields are saved as unspecified. Amounts and tax rates are not recalculated automatically.
          </p>

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={cancelEditing}
              disabled={saving}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-white disabled:opacity-50"
            >
              Cancel
            </button>

            <button
              type="submit"
              disabled={saving || deleting}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving
                ? "Saving..."
                : activeForm === "new"
                  ? "Add line item"
                  : "Save changes"}
            </button>
          </div>
        </form>
      )}

      {deleteTargetId !== null && (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50/50 p-4">
          <h3 className="text-sm font-semibold text-gray-900">
            Delete line item
          </h3>

          <p className="mt-1 text-xs text-gray-600">
            This operation will be recorded in the invoice activity history.
          </p>

          <label className="mt-3 block">
            <span className="mb-1 block text-xs font-medium text-gray-600">
              Reason for deletion
            </span>

            <textarea
              value={deleteReason}
              onChange={(event) => setDeleteReason(event.target.value)}
              rows={2}
              maxLength={1000}
              required
              placeholder="Explain why this line item should be removed."
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100"
            />
          </label>

          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setDeleteTargetId(null);
                setDeleteReason("");
                setError(null);
              }}
              disabled={deleting}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-white disabled:opacity-50"
            >
              Cancel
            </button>

            <button
              type="button"
              onClick={() => handleDelete(deleteTargetId)}
              disabled={deleting || saving || !deleteReason.trim()}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {deleting ? "Deleting..." : "Confirm deletion"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Evidence                                                                   */
/* -------------------------------------------------------------------------- */

function EvidenceSection({
  fieldEvidence,
  fieldConfidence,
}: {
  fieldEvidence: DataRecord;
  fieldConfidence: DataRecord;
}) {
  const evidenceEntries = Object.entries(fieldEvidence);

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <h2 className="text-base font-semibold text-gray-900">
        Extraction evidence
      </h2>

      <p className="mt-1 text-xs text-gray-500">
        Source quotations supplied by the extraction model.
        These quotations have not necessarily been semantically verified.
      </p>

      {evidenceEntries.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">
          No source evidence was recorded.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {evidenceEntries.map(([fieldName, rawEvidence]) => {
            const evidenceItems = Array.isArray(rawEvidence)
              ? rawEvidence.map(asRecord)
              : [];

            const confidence = fieldConfidence[fieldName];

            const validConfidence =
              confidence !== null &&
              confidence !== undefined &&
              Number.isFinite(Number(confidence));

            return (
              <div
                key={fieldName}
                className="rounded-lg border border-gray-100 p-3"
              >
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-sm font-medium text-gray-800">
                    {formatKey(fieldName)}
                  </span>

                  <span className="text-xs text-gray-500">
                    Model score:{" "}
                    {validConfidence
                      ? `${Math.round(Number(confidence) * 100)}%`
                      : "Not available"}
                  </span>
                </div>

                {evidenceItems.length === 0 ? (
                  <p className="mt-2 text-xs text-gray-500">
                    No supporting quotation supplied.
                  </p>
                ) : (
                  evidenceItems.map((item, index) => (
                    <div
                      key={index}
                      className="mt-2 rounded-md bg-gray-50 p-2"
                    >
                      <p className="whitespace-pre-wrap text-xs text-gray-700">
                        {`"${displayValue(item.quote)}"`}
                      </p>

                      <p className="mt-1 text-xs text-gray-400">
                        Page {displayValue(item.page)}
                      </p>
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-4 text-xs text-amber-700">
        Model confidence scores are currently informational only.
        They must not be used as proof that an extracted value is correct.
      </p>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Vendor assignment                                                          */
/* -------------------------------------------------------------------------- */

function VendorAssignmentSection({
  organizationId,
  invoiceId,
  extractedSupplier,
  matchedVendor,
  onAssigned,
}: {
  organizationId: string;
  invoiceId: string;
  extractedSupplier: DataRecord;
  matchedVendor: DataRecord;
  onAssigned: () => Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [selectedVendorId, setSelectedVendorId] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

    const [showCreateForm, setShowCreateForm] = useState(false);

  const [newVendorLegalName, setNewVendorLegalName] = useState(
    typeof extractedSupplier.legal_name === "string"
      ? extractedSupplier.legal_name
      : "",
  );

  const [newVendorDisplayName, setNewVendorDisplayName] = useState("");
  const [newVendorCode, setNewVendorCode] = useState("");
  const [newVendorTin, setNewVendorTin] = useState("");
  const [newVendorEmail, setNewVendorEmail] = useState("");
  const [newVendorPhone, setNewVendorPhone] = useState("");
  const [newVendorAddress, setNewVendorAddress] = useState("");

  useEffect(() => {
    let active = true;

    async function loadVendors() {
      setLoading(true);
      setError("");

      try {
        const result = await fetchVendors(
          organizationId,
          search,
        );

        if (active) {
          setVendors(result.results);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load registered vendors.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadVendors();

    return () => {
      active = false;
    };
  }, [organizationId, search]);

  async function handleAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedVendorId) {
      setError("Please select a vendor.");
      return;
    }

    if (!correctionReason.trim()) {
      setError("Please provide a correction reason.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      await assignInvoiceVendor(
        organizationId,
        invoiceId,
        selectedVendorId,
        correctionReason.trim(),
      );

      await onAssigned();

      setSuccess("Vendor assigned successfully.");
      setSelectedVendorId("");
      setCorrectionReason("");
      setSearch("");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to assign vendor.",
      );
    } finally {
      setSaving(false);
    }
  }

    async function handleCreateVendor(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    const legalName = newVendorLegalName.trim();

    if (!legalName) {
      setError("Vendor legal name is required.");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");

    let createdVendor: Vendor;

    // Stage 1: Create the vendor.
    try {
      const result = await createVendor(
        organizationId,
        {
          legal_name: legalName,
          display_name: newVendorDisplayName.trim(),
          vendor_code: newVendorCode.trim(),
          tax_identification_number: newVendorTin.trim(),
          email: newVendorEmail.trim(),
          phone: newVendorPhone.trim(),
          address: newVendorAddress.trim(),
        },
      );

      createdVendor = result.vendor;

      // Make the new vendor immediately available
      // in the existing vendor-selection list.
      setVendors((current) => {
        const alreadyExists = current.some(
          (vendor) => vendor.id === createdVendor.id,
        );

        if (alreadyExists) {
          return current;
        }

        return [...current, createdVendor].sort(
          (a, b) => a.legal_name.localeCompare(b.legal_name),
        );
      });

      setSelectedVendorId(createdVendor.id);

      setShowCreateForm(false);

    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create vendor.",
      );

      setSaving(false);
      return;
    }

    // Stage 2: Assign the successfully created vendor.
    const assignmentReason =
      "New vendor created after verifying the supplier details against the invoice.";

    setCorrectionReason(assignmentReason);

    try {
      await assignInvoiceVendor(
        organizationId,
        invoiceId,
        createdVendor.id,
        assignmentReason,
      );
    } catch (err) {
      setError(
        `Vendor created successfully, but invoice assignment failed: ${
          err instanceof Error
            ? err.message
            : "Unknown error."
        } The vendor remains selected below. Use Assign vendor to retry.`,
      );

      setSaving(false);
      return;
    }

    setSuccess("Vendor created and assigned successfully.");

    setCorrectionReason("");
    setSelectedVendorId("");
    setSearch("");

    try {
      await onAssigned();
    } catch {
      setError(
        "Vendor was assigned successfully, but the invoice could not refresh. Reload the page.",
      );
    } finally {
      setSaving(false);
    }
  }

  const selectedVendor = vendors.find(
    (vendor) => vendor.id === selectedVendorId,
  );

  const matchedVendorName =
    matchedVendor.display_name ??
    matchedVendor.legal_name ??
    matchedVendor.name;

  const extractedName = extractedSupplier.legal_name;
  const extractedTin = extractedSupplier.tax_identification_number;
  const extractedAddress = extractedSupplier.address;

  const currentVendorId =
    typeof matchedVendor.id === "string"
      ? matchedVendor.id
      : "";

  const alreadyAssigned =
    Boolean(currentVendorId) &&
    selectedVendorId === currentVendorId;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-gray-900">
          Supplier verification
        </h2>

        <div className="flex flex-wrap items-center gap-2">
          {currentVendorId ? (
            <span className="rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700">
              Vendor matched
            </span>
          ) : (
            <>
              <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
                Unmatched supplier
              </span>

              <button
                type="button"
                onClick={() => {
                  setShowCreateForm((current) => !current);
                  setError("");
                  setSuccess("");
                }}
                className="rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
              >
                {showCreateForm
                  ? "Cancel creation"
                  : "Create vendor"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Extracted supplier */}
      <div className="rounded-lg bg-gray-50 p-4">
        <p className="text-xs font-medium text-gray-500">
          Supplier extracted from invoice
        </p>

        <p className="mt-1 font-semibold text-gray-900">
          {displayValue(extractedName)}
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-xs text-gray-500">
              Tax identification number
            </p>

            <p className="mt-1 text-sm text-gray-800">
              {displayValue(extractedTin)}
            </p>
          </div>

          <div>
            <p className="text-xs text-gray-500">
              Address
            </p>

            <p className="mt-1 text-sm text-gray-800">
              {displayValue(extractedAddress)}
            </p>
          </div>
        </div>
      </div>

      {/* Current assignment */}
      <div className="mt-4">
        <p className="text-xs font-medium text-gray-500">
          Currently assigned vendor
        </p>

          {showCreateForm && !currentVendorId && (
            <form
              onSubmit={handleCreateVendor}
              className="mt-5 space-y-4 rounded-xl border border-blue-200 bg-blue-50/50 p-4"
            >
              <div>
                <h3 className="font-semibold text-gray-900">
                  Create new vendor
                </h3>

                <p className="mt-1 text-xs text-gray-600">
                  Confirm the supplier&apos;s registered details before
                  creating the vendor record. The new vendor will
                  be assigned to this invoice automatically.
                </p>
              </div>

              <div>
                <label
                  htmlFor="new-vendor-legal-name"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Legal name *
                </label>

                <input
                  id="new-vendor-legal-name"
                  type="text"
                  required
                  maxLength={255}
                  value={newVendorLegalName}
                  onChange={(event) =>
                    setNewVendorLegalName(event.target.value)
                  }
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label
                  htmlFor="new-vendor-display-name"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Display name
                </label>

                <input
                  id="new-vendor-display-name"
                  type="text"
                  maxLength={255}
                  value={newVendorDisplayName}
                  onChange={(event) =>
                    setNewVendorDisplayName(event.target.value)
                  }
                  placeholder="Optional trading or shortened name"
                  className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label
                    htmlFor="new-vendor-code"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Vendor code
                  </label>

                  <input
                    id="new-vendor-code"
                    type="text"
                    maxLength={50}
                    value={newVendorCode}
                    onChange={(event) =>
                      setNewVendorCode(event.target.value)
                    }
                    placeholder="Optional"
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="new-vendor-tin"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Tax identification number
                  </label>

                  <input
                    id="new-vendor-tin"
                    type="text"
                    maxLength={50}
                    value={newVendorTin}
                    onChange={(event) =>
                      setNewVendorTin(event.target.value)
                    }
                    placeholder="Optional"
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="new-vendor-email"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Email
                  </label>

                  <input
                    id="new-vendor-email"
                    type="email"
                    value={newVendorEmail}
                    onChange={(event) =>
                      setNewVendorEmail(event.target.value)
                    }
                    placeholder="Optional"
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="new-vendor-phone"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Phone
                  </label>

                  <input
                    id="new-vendor-phone"
                    type="tel"
                    maxLength={30}
                    value={newVendorPhone}
                    onChange={(event) =>
                      setNewVendorPhone(event.target.value)
                    }
                    placeholder="Optional"
                    className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="new-vendor-address"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Address
                </label>

                <textarea
                  id="new-vendor-address"
                  rows={2}
                  value={newVendorAddress}
                  onChange={(event) =>
                    setNewVendorAddress(event.target.value)
                  }
                  placeholder="Optional"
                  className="w-full rounded-lg border border-gray-200 bg-white p-3 text-sm outline-none focus:border-blue-500"
                />
              </div>

              <button
                type="submit"
                disabled={
                  saving ||
                  !newVendorLegalName.trim()
                }
                className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving
                  ? "Creating and assigning..."
                  : "Create vendor and assign to invoice"}
              </button>
            </form>
          )}

        <p className="mt-1 text-sm font-semibold text-gray-900">
          {matchedVendorName
            ? displayValue(matchedVendorName)
            : "No registered vendor assigned"}
        </p>
      </div>

      <div className="my-5 border-t border-gray-100" />

      <form onSubmit={handleAssignment} className="space-y-4">
        <div>
          <label
            htmlFor="vendor-search"
            className="mb-2 block text-sm font-semibold text-gray-700"
          >
            Find a registered vendor
          </label>

          <input
            id="vendor-search"
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setSelectedVendorId("");
            }}
            placeholder="Search by name, vendor code or TIN..."
            className="h-11 w-full rounded-lg border border-gray-200 px-3 text-sm outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label
            htmlFor="vendor-selection"
            className="mb-2 block text-sm font-semibold text-gray-700"
          >
            Select vendor
          </label>

          <select
            id="vendor-selection"
            value={selectedVendorId}
            onChange={(event) =>
              setSelectedVendorId(event.target.value)
            }
            disabled={loading || vendors.length === 0}
            className="h-11 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm outline-none focus:border-blue-500 disabled:bg-gray-50"
          >
            <option value="">
              {loading
                ? "Loading vendors..."
                : vendors.length === 0
                  ? "No active vendors found"
                  : "Choose a registered vendor"}
            </option>

            {vendors.map((vendor) => (
              <option key={vendor.id} value={vendor.id}>
                {vendor.display_name || vendor.legal_name}
                {vendor.vendor_code
                  ? ` (${vendor.vendor_code})`
                  : ""}
              </option>
            ))}
          </select>
        </div>

        {selectedVendor && (
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
            <p className="text-sm font-semibold text-blue-900">
              Selected vendor details
            </p>

            <p className="mt-2 text-sm text-blue-800">
              {selectedVendor.legal_name}
            </p>

            <p className="mt-1 text-xs text-blue-700">
              TIN:{" "}
              {selectedVendor.tax_identification_number ??
                "Not provided"}
            </p>

            <p className="mt-1 text-xs text-blue-700">
              Address:{" "}
              {selectedVendor.address ?? "Not provided"}
            </p>
          </div>
        )}

        <div>
          <label
            htmlFor="vendor-correction-reason"
            className="mb-2 block text-sm font-semibold text-gray-700"
          >
            Reason for vendor assignment
          </label>

          <textarea
            id="vendor-correction-reason"
            value={correctionReason}
            onChange={(event) =>
              setCorrectionReason(event.target.value)
            }
            maxLength={1000}
            required
            rows={3}
            placeholder="Explain why this registered vendor matches the invoice supplier..."
            className="w-full rounded-lg border border-gray-200 p-3 text-sm outline-none focus:border-blue-500"
          />
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </p>
        )}

        {success && (
          <p
            role="status"
            className="rounded-lg bg-green-50 p-3 text-sm text-green-700"
          >
            {success}
          </p>
        )}

        <button
          type="submit"
          disabled={
            saving ||
            loading ||
            !selectedVendorId ||
            !correctionReason.trim() ||
            alreadyAssigned
          }
          className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Assigning vendor..." : "Assign vendor"}
        </button>
      </form>
    </section>
  );
}

type HeaderFormState = {
  invoice_number: string;
  invoice_date: string;
  due_date: string;
  currency: string;
  subtotal: string;
  other_charges: string;
  total_amount: string;
  amount_due: string;
  description: string;
  correction_reason: string;
};

function HeaderInput({
  label,
  name,
  value,
  onChange,
  type = "text",
  step,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "date" | "number";
  step?: string;
}) {
  return (
    <div>
      <label
        htmlFor={name}
        className="mb-1.5 block text-xs font-semibold text-gray-600"
      >
        {label}
      </label>

      <input
        id={name}
        name={name}
        type={type}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-gray-200 px-3 text-sm text-gray-900 outline-none focus:border-blue-500"
      />
    </div>
  );
}

function InvoiceHeaderEditor({
  organizationId,
  invoiceId,
  invoice,
  financialData,
  onCancel,
  onSaved,
}: {
  organizationId: string;
  invoiceId: string;
  invoice: DataRecord;
  financialData: DataRecord;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<HeaderFormState>({
    invoice_number: String(invoice.invoice_number ?? ""),
    invoice_date: String(invoice.invoice_date ?? ""),
    due_date: String(invoice.due_date ?? ""),
    currency: String(invoice.currency ?? "NGN"),
    subtotal: String(financialData.subtotal ?? ""),
    other_charges: String(financialData.other_charges ?? ""),
    total_amount: String(financialData.total_amount ?? ""),
    amount_due: String(financialData.amount_due ?? ""),
    description: String(invoice.description ?? ""),
    correction_reason: "",
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function updateField(
    field: keyof HeaderFormState,
    value: string,
  ) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function nullableValue(value: string): string | null {
    return value.trim() === "" ? null : value.trim();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!form.correction_reason.trim()) {
      setError("Please provide a correction reason.");
      return;
    }

    const corrections: InvoiceHeaderCorrections = {
      invoice_number: form.invoice_number.trim(),
      invoice_date: nullableValue(form.invoice_date),
      due_date: nullableValue(form.due_date),
      currency: nullableValue(form.currency)?.toUpperCase() ?? null,
      subtotal: nullableValue(form.subtotal),
      other_charges: nullableValue(form.other_charges),
      total_amount: nullableValue(form.total_amount),
      amount_due: nullableValue(form.amount_due),
      description: form.description.trim(),
      correction_reason: form.correction_reason.trim(),
    };

    setSaving(true);
    setError("");

    try {
      await updateInvoiceHeader(
        organizationId,
        invoiceId,
        corrections,
      );

      await onSaved();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save invoice corrections.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-blue-200 bg-white p-5">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            Edit invoice information
          </h2>

          <p className="mt-1 text-xs text-gray-500">
            Verify and correct the extracted values against the original PDF.
          </p>
        </div>

        <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
          Correction mode
        </span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Basic invoice details */}
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-800">
            Invoice details
          </h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <HeaderInput
              label="Invoice number"
              name="invoice_number"
              value={form.invoice_number}
              onChange={(value) =>
                updateField("invoice_number", value)
              }
            />

            <HeaderInput
              label="Currency"
              name="currency"
              value={form.currency}
              onChange={(value) =>
                updateField("currency", value)
              }
            />

            <HeaderInput
              label="Invoice date"
              name="invoice_date"
              type="date"
              value={form.invoice_date}
              onChange={(value) =>
                updateField("invoice_date", value)
              }
            />

            <HeaderInput
              label="Due date"
              name="due_date"
              type="date"
              value={form.due_date}
              onChange={(value) =>
                updateField("due_date", value)
              }
            />
          </div>

          <div className="mt-4">
            <label
              htmlFor="invoice-description"
              className="mb-1.5 block text-xs font-semibold text-gray-600"
            >
              Description
            </label>

            <textarea
              id="invoice-description"
              value={form.description}
              onChange={(event) =>
                updateField("description", event.target.value)
              }
              rows={3}
              className="w-full rounded-lg border border-gray-200 p-3 text-sm outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div className="border-t border-gray-100 pt-5">
          <h3 className="mb-3 text-sm font-semibold text-gray-800">
            Financial details
          </h3>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <HeaderInput
              label="Subtotal"
              name="subtotal"
              type="number"
              step="0.01"
              value={form.subtotal}
              onChange={(value) =>
                updateField("subtotal", value)
              }
            />

            <HeaderInput
              label="Other charges"
              name="other_charges"
              type="number"
              step="0.01"
              value={form.other_charges}
              onChange={(value) =>
                updateField("other_charges", value)
              }
            />

            <HeaderInput
              label="Total amount"
              name="total_amount"
              type="number"
              step="0.01"
              value={form.total_amount}
              onChange={(value) =>
                updateField("total_amount", value)
              }
            />

            <HeaderInput
              label="Amount due"
              name="amount_due"
              type="number"
              step="0.01"
              value={form.amount_due}
              onChange={(value) =>
                updateField("amount_due", value)
              }
            />
          </div>

          <div className="mt-4 rounded-lg bg-gray-50 p-3">
            <p className="text-xs font-medium text-gray-500">
              Recorded tax amount (read-only)
            </p>

            <p className="mt-1 text-sm font-semibold text-gray-800">
              {formatMoney(financialData.tax_amount, form.currency)}
            </p>

            <p className="mt-1 text-xs text-gray-500">
              Tax amount is not currently editable through the header correction API.
            </p>
          </div>
        </div>

        {/* Correction reason */}
        <div className="border-t border-gray-100 pt-5">
          <label
            htmlFor="header-correction-reason"
            className="mb-2 block text-sm font-semibold text-gray-700"
          >
            Reason for correction
          </label>

          <textarea
            id="header-correction-reason"
            value={form.correction_reason}
            onChange={(event) =>
              updateField("correction_reason", event.target.value)
            }
            maxLength={1000}
            required
            rows={3}
            placeholder="Explain why these invoice details are being corrected..."
            className="w-full rounded-lg border border-gray-200 p-3 text-sm outline-none focus:border-blue-500"
          />

          <p className="mt-1 text-right text-xs text-gray-400">
            {form.correction_reason.length}/1000
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-lg border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>

          <button
            type="submit"
            disabled={saving || !form.correction_reason.trim()}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? "Saving corrections..." : "Save corrections"}
          </button>
        </div>
      </form>
    </section>
  );
}

function InvoiceSubmissionSection({
  organizationId,
  invoiceId,
  status,
  onSubmitted,
}: {
  organizationId: string;
  invoiceId: string;
  status: string;
  onSubmitted: () => Promise<void>;
}) {
  const [submissionNote, setSubmissionNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<
    InvoiceSubmissionError["blockers"]
  >([]);
  const [submitted, setSubmitted] = useState(false);

  const canSubmit =
    status === "needs_review" && !submitted;

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!canSubmit || saving) {
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);
    setBlockers([]);

    try {
      const result = await submitInvoiceForApproval(
        organizationId,
        invoiceId,
        submissionNote,
      );

      setSubmitted(true);
      setSuccess(result.message);
      setSubmissionNote("");

      try {
        await onSubmitted();
      } catch {
        setError(
          "The invoice was submitted successfully, but the page could not refresh. Reload it to see the updated status.",
        );
      }
    } catch (err) {
      if (err instanceof InvoiceSubmissionError) {
        setError(err.message);
        setBlockers(err.blockers);
      } else {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to submit the invoice.",
        );
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            Submit for approval
          </h2>

          <p className="mt-1 text-xs text-gray-500">
            Submit the reviewed invoice into the maker-checker approval workflow.
          </p>
        </div>

        {status === "pending_approval" && (
          <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-700">
            Pending approval
          </span>
        )}
      </div>

      {status === "pending_approval" ? (
        <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
          This invoice has been submitted and is awaiting an authorized approver&apos;s decision.
        </p>
      ) : status === "needs_review" ? (
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">
              Submission note
              <span className="ml-1 font-normal text-gray-400">
                (optional)
              </span>
            </span>

            <textarea
              value={submissionNote}
              onChange={(event) =>
                setSubmissionNote(event.target.value)
              }
              rows={3}
              maxLength={1000}
              disabled={saving || submitted}
              placeholder="Add context for the person reviewing this invoice for approval."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-gray-50"
            />

            <span className="mt-1 block text-right text-xs text-gray-400">
              {submissionNote.length}/1000
            </span>
          </label>

          <button
            type="submit"
            disabled={!canSubmit || saving}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving
              ? "Submitting..."
              : "Submit for approval"}
          </button>
        </form>
      ) : (
        <p className="mt-4 text-sm text-gray-600">
          Submission is unavailable while this invoice has status:{" "}
          <strong>{formatKey(status)}</strong>.
        </p>
      )}

      {success && (
        <p
          role="status"
          className="mt-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700"
        >
          {success}
        </p>
      )}

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3"
        >
          <p className="text-sm font-medium text-red-800">
            {error}
          </p>
        </div>
      )}

      {blockers.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-900">
            Review blockers
          </h3>

          <p className="mt-1 text-xs text-amber-800">
            Address these issues before submitting the invoice.
          </p>

          <ul className="mt-3 space-y-3">
            {blockers.map((blocker, index) => (
              <li
                key={`${blocker.code}-${blocker.field_name}-${index}`}
                className="border-l-2 border-amber-400 pl-3"
              >
                <p className="text-sm font-semibold text-amber-900">
                  {formatKey(blocker.code)}
                </p>

                <p className="mt-1 text-xs text-amber-800">
                  Field: {formatKey(blocker.field_name)}
                </p>

                <p className="mt-1 text-sm text-amber-900">
                  {blocker.message}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Invoice review workspace                                                   */
/* -------------------------------------------------------------------------- */

function InvoiceReviewWorkspace() {
  const [editingHeader, setEditingHeader] = useState(false);
  const params = useParams<{ invoiceId: string }>();
  const searchParams = useSearchParams();

  const invoiceId = params.invoiceId;
  const organizationId = searchParams.get("organizationId") ?? "";

  const [review, setReview] = useState<InvoiceReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadReview() {
      if (!organizationId || !invoiceId) {
        setError("The organization or invoice ID is missing.");
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const result = await fetchInvoiceReview(
          organizationId,
          invoiceId,
        );

        if (active) {
          setReview(result);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load invoice review.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadReview();

    return () => {
      active = false;
    };
  }, [organizationId, invoiceId]);

  async function refreshReview() {
    const result = await fetchInvoiceReview(
      organizationId,
      invoiceId,
    );

    setReview(result);
  }

  if (loading) {
    return (
      <main className="p-8">
        <p className="text-sm text-gray-500">
          Loading invoice review...
        </p>
      </main>
    );
  }

  if (error || !review) {
    return (
      <main className="space-y-4 p-8">
        <Link
          href="/invoices"
          className="text-sm text-blue-600 hover:underline"
        >
          ← Back to invoices
        </Link>

        <div className="rounded-xl border border-red-200 bg-red-50 p-5">
          <h1 className="font-semibold text-red-800">
            Unable to load invoice
          </h1>

          <p className="mt-2 text-sm text-red-700">
            {error ?? "The invoice review could not be loaded."}
          </p>
        </div>
      </main>
    );
  }

  const invoice = asRecord(review.invoice);
  const supplier = asRecord(review.supplier);
  const extraction = asRecord(review.extraction);
  const validation = asRecord(review.validation);

  const originalData = asRecord(extraction.original_data);
  const financialData = asRecord(invoice.financial_data);

  const fieldEvidence = asRecord(extraction.field_evidence);
  const fieldConfidence = asRecord(extraction.field_confidence);

  const extractedSupplier = asRecord(supplier.extracted_supplier);
  const matchedVendor = asRecord(supplier.matched_vendor);

  const currency =
    typeof invoice.currency === "string"
      ? invoice.currency
      : "NGN";

  const lineItemsFromAPI = Array.isArray(review.line_items)
    ? review.line_items
    : [];

  const extractedLineItems = Array.isArray(originalData.line_items)
    ? originalData.line_items
    : [];

  const lineItems =
    lineItemsFromAPI.length > 0
      ? lineItemsFromAPI
      : extractedLineItems;

  const taxes = Array.isArray(originalData.taxes)
    ? originalData.taxes
    : [];

  const warnings = Array.isArray(extraction.warnings)
    ? extraction.warnings
    : [];

  const validationIssues = Array.isArray(validation.issues)
    ? validation.issues
    : [];

  const auditHistory = Array.isArray(review.audit_history)
    ? review.audit_history
    : [];

  // The API's invoice field is named "number".
  const invoiceNumber = formatValue(
    invoice.number ?? originalData.invoice_number,
  );

  const status = formatValue(invoice.status);

  const document = asRecord(review.document);

  const documentId =
    typeof document.id === "string" ? document.id : "";

  const documentName =
    typeof document.original_filename === "string"
      ? document.original_filename
      : "No document attached";

  const previewUrl = documentId
    ? getInvoiceDocumentPreviewUrl(
        organizationId,
        documentId,
      )
    : null;

  return (
    <main className="min-h-screen bg-gray-50">
      {/* Page header */}
      <header className="border-b border-gray-200 bg-white px-6 py-5">
        <div className="mx-auto max-w-[1800px]">
          <Link
            href="/invoices"
            className="text-sm text-blue-600 hover:underline"
          >
            ← Back to invoices
          </Link>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold text-gray-900">
                Invoice {invoiceNumber}
              </h1>

              <p className="mt-1 text-sm text-gray-500">
                Review extracted information against the original document.
              </p>
            </div>

            <span className="rounded-full bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
              {status}
            </span>
          </div>
        </div>
      </header>

      {/* Review workspace */}
      <div className="mx-auto grid max-w-[1800px] grid-cols-1 gap-6 p-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">

        {/* Original PDF */}
        <section className="min-w-0">
          <div className="mb-3">
            <h2 className="text-base font-semibold text-gray-900">
              Original invoice
            </h2>

            <p className="mt-1 text-sm text-gray-500">
              {documentName}
            </p>
          </div>

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            {previewUrl ? (
              <iframe
                key={documentId}
                src={previewUrl}
                title="Original invoice PDF"
                className="h-[75vh] min-h-[550px] w-full"
              />
            ) : (
              <div className="flex min-h-[550px] items-center justify-center p-6">
                <p className="text-sm text-gray-500">
                  No PDF document is available for this invoice.
                </p>
              </div>
            )}
          </div>
        </section>

        {/* Review information */}
        <div className="min-w-0 space-y-5 lg:max-h-[85vh] lg:overflow-y-auto lg:pr-2">

          {editingHeader ? (
          <InvoiceHeaderEditor
            organizationId={organizationId}
            invoiceId={invoiceId}
            invoice={invoice}
            financialData={financialData}
            onCancel={() => setEditingHeader(false)}
            onSaved={async () => {
              await refreshReview();
              setEditingHeader(false);
            }}
          />
        ) : (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                Invoice details
              </h2>

              <button
                type="button"
                onClick={() => setEditingHeader(true)}
                disabled={invoice.status !== "needs_review"}
                className="rounded-lg border border-blue-200 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Edit invoice
              </button>
            </div>

            {/* Invoice information */}
            <section className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="mb-4 text-base font-semibold text-gray-900">
                Invoice information
              </h2>

              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <ReviewField
                  label="Invoice number"
                  value={invoice.invoice_number ?? originalData.invoice_number}
                  fieldName="invoice_number"
                  confidence={fieldConfidence.invoice_number}
                  evidence={fieldEvidence.invoice_number}
                />

                <ReviewField
                  label="Invoice date"
                  value={invoice.invoice_date}
                  fieldName="invoice_date"
                  confidence={fieldConfidence.invoice_date}
                  evidence={fieldEvidence.invoice_date}
                />

                <ReviewField
                  label="Due date"
                  value={invoice.due_date}
                  fieldName="due_date"
                  confidence={fieldConfidence.due_date}
                  evidence={fieldEvidence.due_date}
                />

                <ReviewField
                  label="Currency"
                  value={currency}
                  fieldName="currency"
                  confidence={fieldConfidence.currency}
                  evidence={fieldEvidence.currency}
                />

                <div className="sm:col-span-2">
                  <ReviewField
                    label="Description"
                    value={invoice.description}
                    fieldName="description"
                    confidence={fieldConfidence.description}
                    evidence={fieldEvidence.description}
                  />
                </div>
              </dl>
            </section>

            {/* Financial summary */}
            <section className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="mb-4 text-base font-semibold text-gray-900">
                Financial summary
              </h2>

              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <ReviewField
                  label="Subtotal"
                  value={financialData.subtotal}
                  fieldName="subtotal"
                  money
                  currency={currency}
                  confidence={fieldConfidence.subtotal}
                  evidence={fieldEvidence.subtotal}
                />

                <ReviewField
                  label="Tax amount"
                  value={financialData.tax_amount}
                  fieldName="taxes"
                  money
                  currency={currency}
                  confidence={fieldConfidence.taxes}
                  evidence={fieldEvidence.taxes}
                />

                <ReviewField
                  label="Other charges"
                  value={financialData.other_charges}
                  fieldName="other_charges"
                  money
                  currency={currency}
                  confidence={fieldConfidence.other_charges}
                  evidence={fieldEvidence.other_charges}
                />

                <ReviewField
                  label="Amount due"
                  value={financialData.amount_due}
                  fieldName="amount_due"
                  money
                  currency={currency}
                  confidence={fieldConfidence.amount_due}
                  evidence={fieldEvidence.amount_due}
                />
              </dl>

              <div className="mt-4 flex items-center justify-between rounded-lg bg-gray-50 p-4">
                <span className="text-sm font-semibold text-gray-700">
                  Total invoice amount
                </span>

                <span className="text-lg font-bold text-gray-900">
                  {formatMoney(financialData.total_amount, currency)}
                </span>
              </div>

              {taxes.length > 0 && (
                <div className="mt-5 border-t border-gray-100 pt-4">
                  <h3 className="mb-3 text-sm font-semibold text-gray-800">
                    Extracted taxes
                  </h3>

                  <div className="space-y-2">
                    {taxes.map((rawTax, index) => {
                      const tax = asRecord(rawTax);

                      return (
                        <div
                          key={index}
                          className="flex flex-wrap items-center justify-between gap-2 text-sm"
                        >
                          <div>
                            <p className="font-medium text-gray-800">
                              {displayValue(tax.name)}
                            </p>

                            <p className="text-xs text-gray-500">
                              {displayValue(tax.treatment)}
                              {tax.rate_percent != null
                                ? ` · ${formatValue(tax.rate_percent)}%`
                                : ""}
                            </p>
                          </div>

                          <span className="font-medium text-gray-900">
                            {formatMoney(tax.amount, currency)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>
          </div>
        )}

          {/* Vendor assignment */}
          <VendorAssignmentSection
            organizationId={organizationId}
            invoiceId={invoiceId}
            extractedSupplier={extractedSupplier}
            matchedVendor={matchedVendor}
            onAssigned={refreshReview}
          />

          <LineItemsSection
            items={lineItems}
            currency={currency}
            organizationId={organizationId}
            invoiceId={invoiceId}
            status={String(invoice.status ?? "")}
            onUpdated={refreshReview}
          />

          <InvoiceSubmissionSection
              organizationId={organizationId}
              invoiceId={invoiceId}
              status={String(invoice.status ?? "")}
              onSubmitted={refreshReview}
            />

          {/* Extraction evidence */}
          <EvidenceSection
            fieldEvidence={fieldEvidence}
            fieldConfidence={fieldConfidence}
          />

          {/* Extraction warnings */}
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="mb-3 text-base font-semibold text-gray-900">
              Extraction warnings
            </h2>

            {warnings.length === 0 ? (
              <p className="text-sm text-gray-500">
                No extraction warnings were recorded.
              </p>
            ) : (
              <ul className="space-y-2">
                {warnings.map((warning, index) => (
                  <li
                    key={index}
                    className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800"
                  >
                    {displayValue(warning)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Validation issues */}
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="mb-3 text-base font-semibold text-gray-900">
              Validation issues
            </h2>

            {validationIssues.length === 0 ? (
              <p className="text-sm text-gray-500">
                No validation issues were recorded.
              </p>
            ) : (
              <ul className="space-y-3">
                {validationIssues.map((rawIssue, index) => {
                  const issue = asRecord(rawIssue);
                  const isResolved = issue.status === "resolved";

                  return (
                    <li
                      key={String(issue.id ?? index)}
                      className={`rounded-lg border p-3 ${
                        isResolved
                          ? "border-green-100 bg-green-50/40"
                          : "border-amber-100 bg-amber-50/30"
                      }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-800">
                          {formatKey(
                            String(issue.code ?? "Validation issue"),
                          )}
                        </p>

                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-500">
                            {displayValue(issue.severity)}
                          </span>

                          <span
                            className={`rounded-full px-2 py-1 text-xs font-medium ${
                              isResolved
                                ? "bg-green-100 text-green-700"
                                : "bg-amber-100 text-amber-700"
                            }`}
                          >
                            {isResolved ? "Resolved" : "Open"}
                          </span>
                        </div>
                      </div>

                      <p className="mt-2 text-sm text-gray-600">
                        {displayValue(issue.message)}
                      </p>

                      <p className="mt-2 text-xs text-gray-400">
                        Field: {displayValue(issue.field_name)}
                      </p>

                      {isResolved && issue.resolved_at != null && (
                        <p className="mt-2 text-xs text-green-700">
                          Resolved at: {displayValue(issue.resolved_at)}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Activity history */}
          <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="mb-3 text-base font-semibold text-gray-900">
              Activity history
            </h2>

            {auditHistory.length === 0 ? (
              <p className="text-sm text-gray-500">
                No activity has been recorded.
              </p>
            ) : (
              <ul className="space-y-3">
                {auditHistory.map((rawEvent, index) => {
                  const event = asRecord(rawEvent);
                  const actor = asRecord(event.actor);

                  const presentation = describeAuditEvent(event);

                  return (
                    <li
                      key={String(event.id ?? index)}
                      className="border-l-2 border-gray-200 pl-3"
                    >
                      <p className="text-sm font-medium text-gray-800">
                        {presentation.title}
                      </p>

                      {presentation.details.map((detail, detailIndex) => (
                        <p
                          key={detailIndex}
                          className="mt-1 text-xs text-gray-600"
                        >
                          {detail}
                        </p>
                      ))}

                      {presentation.correctionReason && (
                        <p className="mt-1 text-xs text-gray-600">
                          <span className="font-medium">Reason:</span>{" "}
                          {presentation.correctionReason}
                        </p>
                      )}

                      <p className="mt-1 text-xs text-gray-500">
                        {actor.username
                          ? `By ${formatValue(actor.username)}`
                          : "System activity"}
                      </p>

                      <p className="mt-1 text-xs text-gray-400">
                        {displayValue(event.created_at)}
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

export default function InvoiceReviewPage() {
  return (
    <ProtectedRoute>
      <InvoiceReviewWorkspace />
    </ProtectedRoute>
  );
}
