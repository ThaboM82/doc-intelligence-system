/** Shared types for the RAG chat surface. */

export type MessageRole = "user" | "assistant" | "system";

export interface Citation {
  id: string;
  n: number;
  documentId?: string;
  fileName?: string;
  title?: string;
  page?: number;
  score?: number;
  text?: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  citations?: Citation[];
  confidence?: "high" | "medium" | "low";
  confidenceScore?: number;
  refused?: boolean;
  isStreaming?: boolean;
  error?: string;
}

export interface RagQueryResult {
  answer: string;
  sources: Citation[];
  confidence?: string;
  confidenceScore?: number;
  refused?: boolean;
  processingTimeMs?: number;
}