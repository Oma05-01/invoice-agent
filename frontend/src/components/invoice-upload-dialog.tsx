
"use client";

import { useState, type ChangeEvent } from "react";
import {
  CheckCircle2,
  FileText,
  UploadCloud,
  X,
} from "lucide-react";

type Props = {
  organizationId: string;
  onClose: () => void;
  onUploaded: () => void;
};

type UploadResponse = {
  message: string;
  invoice: {
    id: string;
    invoice_number: string;
    status: string;
  };
  document: {
    id: string;
    filename: string;
    status: string;
  };
};

type CSRFResponse = {
  csrfToken: string;
};

async function getCSRFToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf/", {
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Unable to establish a secure connection.");
  }

  const data: CSRFResponse = await response.json();
  return data.csrfToken;
}

async function getErrorMessage(response: Response): Promise<string> {
  const data = await response.json().catch(() => ({}));

  if (typeof data.detail === "string") {
    return data.detail;
  }

  if (Array.isArray(data.file)) {
    return data.file.join(" ");
  }

  return `Request failed with status ${response.status}.`;
}

export function InvoiceUploadDialog({
  organizationId,
  onClose,
  onUploaded,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [invoiceId, setInvoiceId] = useState<string | null>(null);

  const [uploading, setUploading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [processingQueued, setProcessingQueued] = useState(false);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setError("");
    setMessage("");

    const selectedFile = event.target.files?.[0] ?? null;

    if (!selectedFile) {
      setFile(null);
      return;
    }

    const isPdf =
      selectedFile.type === "application/pdf" ||
      selectedFile.name.toLowerCase().endsWith(".pdf");

    if (!isPdf) {
      setFile(null);
      setError("Please select a PDF document.");
      event.target.value = "";
      return;
    }

    // The backend currently permits uploads up to 10 MB.
    if (selectedFile.size > 10 * 1024 * 1024) {
      setFile(null);
      setError("The PDF must not exceed 10 MB.");
      event.target.value = "";
      return;
    }

    setFile(selectedFile);
  }

  async function queueProcessing(
    targetInvoiceId: string,
    csrfToken: string,
  ) {
    setQueueing(true);
    setError("");

    try {
      const response = await fetch(
        `/api/organizations/${encodeURIComponent(organizationId)}/invoices/${encodeURIComponent(targetInvoiceId)}/process/`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({}),
        },
      );

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      setProcessingQueued(true);
      setMessage(
        "Your invoice has been uploaded and successfully queued for processing.",
      );
    } catch (err) {
      setError(
        `The invoice was uploaded, but processing could not be queued. ${
          err instanceof Error ? err.message : "Please retry."
        }`,
      );
    } finally {
      setQueueing(false);
    }
  }

  async function handleUpload() {
    if (invoiceId || !file) return;

    setUploading(true);
    setError("");
    setMessage("");

    try {
      const csrfToken = await getCSRFToken();

      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(
        `/api/organizations/${encodeURIComponent(organizationId)}/documents/`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": csrfToken,
          },
          body: formData,
        },
      );

      if (!response.ok) {
        throw new Error(await getErrorMessage(response));
      }

      const data: UploadResponse = await response.json();

      setInvoiceId(data.invoice.id);
      setMessage("Invoice uploaded successfully.");

      // Refresh the listing as soon as Django creates the invoice.
      onUploaded();

      // Queue the newly created invoice.
      await queueProcessing(data.invoice.id, csrfToken);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to upload the invoice.",
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleRetryProcessing() {
    if (!invoiceId || processingQueued) return;

    setError("");

    try {
      const csrfToken = await getCSRFToken();
      await queueProcessing(invoiceId, csrfToken);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to retry processing.",
      );
    }
  }

  const busy = uploading || queueing;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onClose();
        }
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="invoice-upload-title"
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <UploadCloud size={22} />
            </div>

            <h2
              id="invoice-upload-title"
              className="text-lg font-bold text-slate-900"
            >
              Upload an invoice
            </h2>

            <p className="mt-1 text-sm text-slate-500">
              Upload a supplier invoice for automated processing.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close upload dialog"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 disabled:opacity-40"
          >
            <X size={19} />
          </button>
        </div>

        {!invoiceId && (
          <label className="mt-6 flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 px-5 py-9 text-center transition hover:border-blue-300 hover:bg-blue-50/40">
            <UploadCloud size={30} className="text-blue-600" />

            <span className="mt-3 text-sm font-semibold text-slate-800">
              Choose a PDF invoice
            </span>

            <span className="mt-1 text-xs text-slate-500">
              Maximum file size: 10 MB
            </span>

            <input
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
              disabled={busy}
              className="sr-only"
            />
          </label>
        )}

        {file && !invoiceId && (
          <div className="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 p-3">
            <FileText size={22} className="shrink-0 text-blue-600" />

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-800">
                {file.name}
              </p>

              <p className="text-xs text-slate-400">
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
          </div>
        )}

        {invoiceId && (
          <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="flex items-center gap-2 text-emerald-800">
              <CheckCircle2 size={19} />
              <span className="text-sm font-semibold">
                Document stored successfully
              </span>
            </div>

            <p className="mt-2 break-all text-xs text-emerald-700">
              Invoice ID: {invoiceId}
            </p>
          </div>
        )}

        {message && (
          <div className="mt-4 text-sm text-emerald-700">
            {message}
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
          >
            {error}
          </div>
        )}

        {!invoiceId && (
          <div className="mt-4 rounded-lg bg-blue-50 p-3 text-xs leading-5 text-blue-800">
            After uploading, FIN-01 creates an invoice record and queues it
            for background extraction and validation.
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            {processingQueued ? "Close" : "Cancel"}
          </button>

          {invoiceId && !processingQueued ? (
            <button
              type="button"
              onClick={handleRetryProcessing}
              disabled={busy}
              className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
            >
              {queueing ? "Queueing..." : "Retry processing"}
            </button>
          ) : !invoiceId ? (
            <button
              type="button"
              onClick={handleUpload}
              disabled={!file || busy}
              className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {uploading
                ? "Uploading..."
                : queueing
                  ? "Queueing..."
                  : "Upload and process"}
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
