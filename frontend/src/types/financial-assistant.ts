export interface FinancialAssistantToolInvocation {
  name: string;
  succeeded: boolean;
}

export interface FinancialAssistantChatRequest {
  question: string;
  conversation_id?: string;
}

export interface FinancialAssistantChatResponse {
  conversation_id: string;
  answer: string;
  model: string;
  tool_call_count: number;
  tool_invocations: FinancialAssistantToolInvocation[];
}

export interface AssistantConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  message_count: number;
}

export interface AssistantConversationListResponse {
  results: AssistantConversationSummary[];
  limit: number;
}

export interface AssistantConversationMessage {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  model: string;
  tool_call_count: number;
  tool_invocations: FinancialAssistantToolInvocation[];
  created_at: string;
}

export interface AssistantConversationDetailResponse {
  conversation: Omit<AssistantConversationSummary, "message_count">;
  messages: AssistantConversationMessage[];
}

/** UI message shape also supports the unsaved user turn while a request is pending. */
export interface FinancialAssistantDisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  model?: string;
  tool_call_count?: number;
  tool_invocations?: FinancialAssistantToolInvocation[];
  created_at?: string;
}
