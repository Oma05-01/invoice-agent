export interface FinancialAssistantToolInvocation {
  name: string;
  succeeded: boolean;
}

export interface FinancialAssistantChatRequest {
  question: string;
}

export interface FinancialAssistantChatResponse {
  answer: string;
  model: string;
  tool_call_count: number;
  tool_invocations: FinancialAssistantToolInvocation[];
}
