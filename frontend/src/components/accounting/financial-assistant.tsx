"use client";

import { useState, type FormEvent } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  Send,
  Sparkles,
  Wrench,
} from "lucide-react";

import { askFinancialAssistant } from "@/lib/financial-assistant";
import type { FinancialAssistantChatResponse } from "@/types/financial-assistant";

type Props = {
  organizationId: string;
};

const suggestedQuestions = [
  "Which vendors account for most of our expenditure this year?",
  "Show our monthly expenditure trend this year.",
  "Break down our expenditure by expense account this year.",
];

function getToolLabel(name: string): string {
  if (name === "spend_by") return "Expenditure report";
  return name.replace(/_/g, " ");
}

export function FinancialAssistant({ organizationId }: Props) {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [result, setResult] = useState<FinancialAssistantChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();

    if (!trimmedQuestion || loading || !organizationId) return;

    setLoading(true);
    setError("");
    setResult(null);
    setSubmittedQuestion(trimmedQuestion);

    try {
      const response = await askFinancialAssistant(
        organizationId,
        trimmedQuestion,
      );
      setResult(response);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The financial assistant could not complete this request.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="w-full space-y-5 p-4 sm:p-6" aria-labelledby="financial-assistant-title">
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-700 text-white shadow-sm">
            <Bot size={22} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="financial-assistant-title" className="text-base font-bold text-slate-900">
                Financial Assistant
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
                <Sparkles size={11} /> AI-assisted
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
              Ask questions about your organisation&apos;s recorded expenditure. The assistant
              retrieves figures from FIN-01&apos;s financial reports; it does not post or change
              accounting entries.
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
          Read-only access
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <Sparkles size={15} className="text-blue-700" />
          <h3 className="text-sm font-semibold text-slate-800">Ask a financial question</h3>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <label htmlFor="financial-assistant-question" className="sr-only">
            Your financial question
          </label>
          <textarea
            id="financial-assistant-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={4}
            maxLength={8000}
            required
            disabled={loading || !organizationId}
            placeholder="For example: Which vendors account for the largest share of our expenditure this year?"
            className="w-full resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50"
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-400">{question.length.toLocaleString()} / 8,000 characters</p>
            <button
              type="submit"
              disabled={loading || !organizationId || !question.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {loading ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={15} />}
              {loading ? "Analysing…" : "Ask assistant"}
            </button>
          </div>
        </form>

        <div className="mt-5 border-t border-slate-100 pt-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Suggested questions
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestedQuestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={loading || !organizationId}
                onClick={() => setQuestion(suggestion)}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>

      {!organizationId && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" role="status">
          Select an organisation before using the Financial Assistant.
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">
          <CircleAlert size={18} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold">The request could not be completed</p>
            <p className="mt-1 leading-6">{error}</p>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-800" role="status" aria-live="polite">
          <LoaderCircle size={18} className="animate-spin" />
          <span>Reviewing the question and retrieving the relevant financial report…</span>
        </div>
      )}

      {result && (
        <article className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 bg-slate-50 px-5 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Your question
            </p>
            <p className="mt-1 text-sm font-medium leading-6 text-slate-800">{submittedQuestion}</p>
          </div>

          <div className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <Bot size={17} />
              </div>
              <h3 className="text-sm font-bold text-slate-900">Assistant response</h3>
            </div>
            <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
              {result.answer}
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <div className="mb-2 flex items-center gap-2">
                <Wrench size={14} className="text-slate-400" />
                <p className="text-xs font-semibold text-slate-600">
                  Financial report lookups ({result.tool_call_count})
                </p>
              </div>
              {result.tool_invocations.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {result.tool_invocations.map((invocation, index) => (
                    <span
                      key={`${invocation.name}-${index}`}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium ${
                        invocation.succeeded
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                          : "border-amber-200 bg-amber-50 text-amber-800"
                      }`}
                    >
                      {invocation.succeeded ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                      {getToolLabel(invocation.name)}
                      <span className="font-normal opacity-75">
                        {invocation.succeeded ? "completed" : "needs review"}
                      </span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs leading-5 text-slate-500">
                  No financial reporting tool was invoked for this response.
                </p>
              )}
            </div>
          </div>
        </article>
      )}

      <p className="text-xs leading-5 text-slate-400">
        Each question is processed independently. Conversation history and follow-up context are not
        retained in this first version. Always verify important decisions against the underlying
        accounting reports.
      </p>
    </section>
  );
}
