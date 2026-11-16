"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  LoaderCircle,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  Wrench,
} from "lucide-react";

import {
  askFinancialAssistant,
  fetchAssistantConversation,
  fetchAssistantConversations,
} from "@/lib/financial-assistant";
import type {
  AssistantConversationSummary,
  FinancialAssistantDisplayMessage,
  FinancialAssistantToolInvocation,
} from "@/types/financial-assistant";

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

function formatConversationDate(value: string | null): string {
  if (!value) return "No messages yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";
  return new Intl.DateTimeFormat("en-NG", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function toDisplayMessage(
  message: {
    id: string;
    role: "user" | "assistant";
    content: string;
    model?: string;
    tool_call_count?: number;
    tool_invocations?: FinancialAssistantToolInvocation[];
    created_at?: string;
  },
): FinancialAssistantDisplayMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    model: message.model,
    tool_call_count: message.tool_call_count,
    tool_invocations: message.tool_invocations,
    created_at: message.created_at,
  };
}

export function FinancialAssistant({ organizationId }: Props) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<FinancialAssistantDisplayMessage[]>([]);
  const [conversations, setConversations] = useState<AssistantConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [conversationListLoading, setConversationListLoading] = useState(true);
  const [error, setError] = useState("");
  const selectionRequestRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    fetchAssistantConversations(organizationId, controller.signal)
      .then((response) => {
        if (!cancelled) setConversations(response.results);
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === "AbortError")) return;
        setError(
          err instanceof Error
            ? err.message
            : "Conversation history could not be loaded.",
        );
      })
      .finally(() => {
        if (!cancelled) setConversationListLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [organizationId]);

  function startNewConversation() {
    selectionRequestRef.current += 1;
    setActiveConversationId(null);
    setMessages([]);
    setQuestion("");
    setError("");
    setHistoryLoading(false);
  }

  async function selectConversation(conversationId: string) {
    if (loading || historyLoading || conversationId === activeConversationId) return;

    const requestId = ++selectionRequestRef.current;
    setActiveConversationId(conversationId);
    setMessages([]);
    setError("");
    setHistoryLoading(true);

    try {
      const response = await fetchAssistantConversation(
        organizationId,
        conversationId,
      );
      if (requestId !== selectionRequestRef.current) return;
      setMessages(response.messages.map(toDisplayMessage));
    } catch (err) {
      if (requestId !== selectionRequestRef.current) return;
      setError(
        err instanceof Error
          ? err.message
          : "This conversation could not be opened.",
      );
    } finally {
      if (requestId === selectionRequestRef.current) setHistoryLoading(false);
    }
  }

  async function refreshConversationList() {
    const response = await fetchAssistantConversations(organizationId);
    setConversations(response.results);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || loading || historyLoading || !organizationId) return;

    const pendingId = `pending-${Date.now()}`;
    const conversationIdAtSubmit = activeConversationId;
    const userMessage: FinancialAssistantDisplayMessage = {
      id: pendingId,
      role: "user",
      content: trimmedQuestion,
    };

    setLoading(true);
    setError("");
    setQuestion("");
    setMessages((current) => [...current, userMessage]);

    try {
      const response = await askFinancialAssistant(
        organizationId,
        trimmedQuestion,
        conversationIdAtSubmit,
      );
      setActiveConversationId(response.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: response.answer,
          model: response.model,
          tool_call_count: response.tool_call_count,
          tool_invocations: response.tool_invocations,
        },
      ]);

      try {
        await refreshConversationList();
      } catch {
        setError("Your response was saved, but the conversation list could not be refreshed.");
      }
    } catch (err) {
      setMessages((current) => current.filter((message) => message.id !== pendingId));
      setQuestion(trimmedQuestion);
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
    <section
      className="w-full space-y-5 p-4 sm:p-6"
      aria-labelledby="financial-assistant-title"
    >
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-700 text-white shadow-sm">
            <Bot size={22} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="financial-assistant-title" className="text-base font-semibold text-slate-900">
                Financial Assistant
              </h2>
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                Read only
              </span>
            </div>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
              Ask questions about your organisation&apos;s financial reports. Your conversations are saved privately to your account.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={startNewConversation}
          disabled={loading || historyLoading}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={15} />
          New conversation
        </button>
      </div>

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="min-w-0 rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between px-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Your conversations
            </h3>
            <MessageSquare size={15} className="text-slate-400" />
          </div>
          {conversationListLoading ? (
            <div className="flex items-center gap-2 px-2 py-4 text-xs text-slate-500">
              <LoaderCircle size={14} className="animate-spin" />
              Loading conversations...
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-4 text-xs leading-5 text-slate-500">
              No saved conversations yet. Ask your first question to start one.
            </p>
          ) : (
            <div className="max-h-[420px] space-y-1 overflow-y-auto">
              {conversations.map((conversation) => {
                const isActive = conversation.id === activeConversationId;
                return (
                  <button
                    key={conversation.id}
                    type="button"
                    onClick={() => void selectConversation(conversation.id)}
                    disabled={loading || historyLoading}
                    aria-current={isActive ? "page" : undefined}
                    className={`w-full rounded-lg border px-3 py-2.5 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${
                      isActive
                        ? "border-blue-200 bg-blue-50"
                        : "border-transparent hover:border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <span className="block truncate text-xs font-semibold text-slate-800">
                      {conversation.title || "New conversation"}
                    </span>
                    <span className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-500">
                      <span className="inline-flex min-w-0 items-center gap-1 truncate">
                        <Clock3 size={11} />
                        {formatConversationDate(conversation.last_message_at)}
                      </span>
                      <span className="shrink-0">
                        {conversation.message_count} messages
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <div className="min-w-0 space-y-4">
          <div className="min-h-[330px] space-y-4 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
            {historyLoading ? (
              <div className="flex min-h-[290px] items-center justify-center gap-2 text-sm text-slate-500">
                <LoaderCircle size={18} className="animate-spin" />
                Loading conversation...
              </div>
            ) : messages.length === 0 ? (
              <div className="flex min-h-[290px] flex-col items-center justify-center text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
                  <Sparkles size={22} />
                </div>
                <h3 className="mt-4 text-sm font-semibold text-slate-900">
                  What would you like to understand?
                </h3>
                <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">
                  Ask about expenditure, vendors or account balances. You can continue a saved conversation with follow-up questions.
                </p>
                <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                  {suggestedQuestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => setQuestion(suggestion)}
                      className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-left text-[11px] font-medium text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                {messages.map((message) => (
                  <article key={message.id} className="space-y-2">
                    <div className={`flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide ${message.role === "user" ? "text-slate-500" : "text-blue-700"}`}>
                      {message.role === "assistant" ? <Bot size={14} /> : <MessageSquare size={13} />}
                      {message.role === "assistant" ? "FIN-01 Assistant" : "You"}
                    </div>
                    <div className={`rounded-xl px-4 py-3 text-sm leading-6 ${message.role === "assistant" ? "border border-slate-200 bg-slate-50 text-slate-700" : "ml-5 bg-blue-50 text-slate-800"}`}>
                      <p className="whitespace-pre-wrap break-words">{message.content}</p>
                    </div>
                    {message.role === "assistant" && (message.tool_call_count ?? 0) > 0 && (
                      <div className="ml-5 flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                          <Wrench size={11} />
                          Financial report lookups ({message.tool_call_count})
                        </span>
                        {(message.tool_invocations ?? []).map((invocation, index) => (
                          <span
                            key={`${message.id}-${invocation.name}-${index}`}
                            className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-medium ${invocation.succeeded ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}
                          >
                            {invocation.succeeded ? <CheckCircle2 size={12} /> : <CircleAlert size={12} />}
                            {getToolLabel(invocation.name)}
                            <span className="font-normal opacity-75">
                              {invocation.succeeded ? "completed" : "needs review"}
                            </span>
                          </span>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" && message.model && (
                      <p className="ml-5 text-[10px] text-slate-400">Model: {message.model}</p>
                    )}
                  </article>
                ))}
                {loading && (
                  <div className="ml-5 flex items-center gap-2 text-xs text-slate-500">
                    <LoaderCircle size={14} className="animate-spin" />
                    Reviewing financial records...
                  </div>
                )}
              </div>
            )}
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs leading-5 text-rose-700">
              <CircleAlert size={15} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3 rounded-xl border border-slate-200 bg-white p-3 sm:p-4">
            <label htmlFor="financial-assistant-question" className="sr-only">
              Your financial question
            </label>
            <textarea
              id="financial-assistant-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={activeConversationId ? "Ask a follow-up question..." : "Ask a question about your organisation's finances..."}
              rows={3}
              maxLength={8000}
              disabled={loading || historyLoading || !organizationId}
              className="w-full resize-y rounded-lg border border-slate-200 px-3 py-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
            />
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-[10px] leading-4 text-slate-400">
                Read-only reporting. Previous messages provide context; financial figures are looked up again from authorised reports.
              </p>
              <button
                type="submit"
                disabled={!question.trim() || loading || historyLoading || !organizationId}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
                {loading ? "Working..." : "Send question"}
              </button>
            </div>
          </form>

          <p className="text-xs leading-5 text-slate-400">
            Conversations are private to your account within this organisation. Verify important decisions against the underlying accounting reports.
          </p>
        </div>
      </div>
    </section>
  );
}
