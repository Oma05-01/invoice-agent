import type {
  AssistantConversationDetailResponse,
  AssistantConversationListResponse,
  FinancialAssistantChatResponse,
} from "@/types/financial-assistant";

type CSRFResponse = {
  csrfToken?: unknown;
};

async function getErrorMessage(response: Response): Promise<string> {
  const data: unknown = await response.json().catch(() => null);

  if (typeof data === "object" && data !== null) {
    if (
      "detail" in data &&
      typeof data.detail === "string" &&
      data.detail.trim()
    ) {
      return data.detail;
    }

    const messages = Object.values(data).flatMap((value) => {
      if (typeof value === "string") return [value];
      if (Array.isArray(value)) {
        return value.filter(
          (item): item is string => typeof item === "string",
        );
      }
      return [];
    });

    if (messages.length > 0) return messages.join(" ");
  }

  return `The financial assistant request failed (${response.status}).`;
}

function conversationBasePath(organizationId: string): string {
  return `/api/organizations/${encodeURIComponent(organizationId)}/insights/assistant`;
}

async function getCSRFToken(): Promise<string> {
  const response = await fetch("/api/auth/csrf/", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(
      "Unable to establish a secure session. Refresh the page and try again.",
    );
  }

  const data = (await response.json()) as CSRFResponse;
  if (typeof data.csrfToken !== "string" || !data.csrfToken) {
    throw new Error(
      "The security token was unavailable. Refresh the page and try again.",
    );
  }

  return data.csrfToken;
}

export async function fetchAssistantConversations(
  organizationId: string,
  signal?: AbortSignal,
): Promise<AssistantConversationListResponse> {
  const response = await fetch(
    `${conversationBasePath(organizationId)}/conversations/`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    },
  );

  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<AssistantConversationListResponse>;
}

export async function fetchAssistantConversation(
  organizationId: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<AssistantConversationDetailResponse> {
  const response = await fetch(
    `${conversationBasePath(organizationId)}/conversations/${encodeURIComponent(conversationId)}/`,
    {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    },
  );

  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<AssistantConversationDetailResponse>;
}

export async function askFinancialAssistant(
  organizationId: string,
  question: string,
  conversationId?: string | null,
): Promise<FinancialAssistantChatResponse> {
  const csrfToken = await getCSRFToken();
  const body: { question: string; conversation_id?: string } = { question };
  if (conversationId) body.conversation_id = conversationId;

  const response = await fetch(
    `${conversationBasePath(organizationId)}/chat/`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );

  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response.json() as Promise<FinancialAssistantChatResponse>;
}
