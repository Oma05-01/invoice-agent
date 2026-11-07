"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";

import { ProtectedRoute } from "@/components/protected-route";
import {
  fetchInvoiceReview,
  getInvoiceDocumentPreviewUrl,
  type InvoiceReviewResponse,
} from "@/lib/invoices";

type DataRecord = Record<string, unknown>;

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

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not provided";
  }

  return formatValue(value);
}

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
    <div data-field-name={fieldName} className="rounded-lg border border-gray-200 p-3">
        
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

function LineItemsSection({
  items,
  currency,
}: {
  items: unknown[];
  currency: string;
}) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">
          Line items
        </h2>

        <span className="text-xs text-gray-500">
          {items.length} item(s)
        </span>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-gray-500">
          No line items were extracted.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500">
                <th className="py-3 pr-4">Description</th>
                <th className="px-3 py-3 text-right">Quantity</th>
                <th className="px-3 py-3 text-right">Unit price</th>
                <th className="px-3 py-3 text-right">Tax rate</th>
                <th className="py-3 pl-3 text-right">Total</th>
              </tr>
            </thead>

            <tbody>
              {items.map((rawItem, index) => {
                const item = asRecord(rawItem);

                return (
                  <tr
                    key={String(item.id ?? index)}
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
                      {item.tax_rate_percent == null
                        ? "Not specified"
                        : `${formatValue(item.tax_rate_percent)}%`}
                    </td>

                    <td className="py-3 pl-3 text-right font-medium text-gray-900">
                      {formatMoney(item.line_total, currency)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

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
                    {confidence == null || !Number.isFinite(Number(confidence))
                        ? "Not available"
                        : `${Math.round(Number(confidence) * 100)}%`}
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
                      {/* For Line 309 */}
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



function InvoiceReviewWorkspace() {
  const params = useParams<{ invoiceId: string }>();
  const searchParams = useSearchParams();

  const invoiceId = params.invoiceId;
  const organizationId = searchParams.get("organizationId") ?? "";

  const [review, setReview] = useState<InvoiceReviewResponse | null>(
    null,
  );
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

const matchedVendorName =
  matchedVendor.legal_name ??
  matchedVendor.display_name ??
  matchedVendor.name;

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

const invoiceNumber = formatValue(
  invoice.invoice_number ?? originalData.invoice_number,
);
const status = formatValue(invoice.status);

  const document = review.document;
  const previewUrl = document
    ? getInvoiceDocumentPreviewUrl(
        organizationId,
        document.id,
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
                Review extracted information against the original
                document.
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
        {/* PDF viewer */}
        <section className="min-w-0">
          <div className="mb-3">
            <h2 className="text-base font-semibold text-gray-900">
              Original invoice
            </h2>

            <p className="mt-1 text-sm text-gray-500">
              {document?.original_filename ?? "No document attached"}
            </p>
          </div>

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            {previewUrl ? (
              <iframe
                key={document?.id}
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

        {/* Extracted invoice information */}
        {/* Invoice review information */}
        <div className="min-w-0 space-y-5 lg:max-h-[85vh] lg:overflow-y-auto lg:pr-2">

        {/* Invoice information */}
        <section className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="mb-4 text-base font-semibold text-gray-900">
            Invoice information
            </h2>

            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ReviewField
                label="Invoice number"
                value={
                invoice.invoice_number ?? originalData.invoice_number
                }
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

        {/* Financial information */}
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

        {/* Supplier information */}
        <section className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold text-gray-900">
                Supplier verification
            </h2>

            {Object.keys(matchedVendor).length > 0 ? (
                <span className="rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700">
                Vendor matched
                </span>
            ) : (
                <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
                Unmatched supplier
                </span>
            )}
            </div>

            <div className="space-y-3">
            <div className="rounded-lg bg-gray-50 p-3">
                <p className="text-xs font-medium text-gray-500">
                Extracted supplier
                </p>

                <p className="mt-1 text-sm font-semibold text-gray-900">
                {displayValue(extractedSupplier.legal_name)}
                </p>

                <p className="mt-1 text-xs text-gray-600">
                {displayValue(extractedSupplier.address)}
                </p>
            </div>

            <ReviewField
                label="Supplier legal name"
                value={extractedSupplier.legal_name}
                fieldName="supplier_legal_name"
                confidence={fieldConfidence.supplier_legal_name}
                evidence={fieldEvidence.supplier_legal_name}
            />

            <ReviewField
                label="Supplier TIN"
                value={extractedSupplier.tax_identification_number}
                fieldName="supplier_tin"
                confidence={fieldConfidence.supplier_tin}
                evidence={fieldEvidence.supplier_tin}
            />

            <ReviewField
                label="Supplier address"
                value={extractedSupplier.address}
                fieldName="supplier_address"
                confidence={fieldConfidence.supplier_address}
                evidence={fieldEvidence.supplier_address}
            />

            <div className="border-t border-gray-100 pt-3">
                <p className="text-xs font-medium text-gray-500">
                Registered vendor
                </p>

                <p className="mt-1 text-sm font-medium text-gray-900">
                {matchedVendorName
                    ? displayValue(matchedVendorName)
                    : "No registered vendor has been matched."}
                </p>
            </div>
            </div>
        </section>

        {/* Line items */}
        <LineItemsSection
            items={lineItems}
            currency={currency}
        />

        {/* Evidence */}
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

                return (
                    <li
                    key={String(issue.id ?? index)}
                    className="rounded-lg border border-gray-100 p-3"
                    >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-800">
                        {formatKey(String(issue.code ?? "Validation issue"))}
                        </p>

                        <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">
                        {displayValue(issue.severity)}
                        </span>
                    </div>

                    <p className="mt-2 text-sm text-gray-600">
                        {displayValue(issue.message)}
                    </p>

                    <p className="mt-2 text-xs text-gray-400">
                        Field: {displayValue(issue.field_name)}
                    </p>
                    </li>
                );
                })}
            </ul>
            )}
        </section>

        {/* Audit history */}
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

                return (
                    <li
                    key={String(event.id ?? index)}
                    className="border-l-2 border-gray-200 pl-3"
                    >
                    <p className="text-sm font-medium text-gray-800">
                        {formatKey(String(event.action ?? "Activity"))}
                    </p>

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