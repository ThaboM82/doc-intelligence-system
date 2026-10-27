/**
 * RAGChat — document Q&A with structured citations + markdown answers.
 */
import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Send,
  Bot,
  User,
  FileText,
  Loader2,
  Sparkles,
  AlertCircle,
  Trash2,
  Square,
  MessageSquare,
  Copy,
  Check,
  RotateCcw,
  X,
  Quote,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { apiClient, type ApiErrorDetails } from "../../lib/apiClient";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Source = {
  n?: number;
  id?: string;
  title?: string;
  file_name?: string;
  source_file?: string;
  page?: number;
  similarity?: number;
  score?: number;
  text?: string;
  chunk_id?: string;
  document_id?: string;
  [key: string]: unknown;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  confidence?: number;
  latencyMs?: number;
  isError?: boolean;
  /** User text that produced this assistant turn (for retry) */
  prompt?: string;
};

// ---------------------------------------------------------------------------
// Constants / helpers
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  "How long are customer account records retained?",
  "What is the critical threat escalation policy?",
  "Summarize quarantine handling for flagged documents.",
];

const MAX_INPUT = 4000;

function newId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function errorMessage(err: unknown): string {
  const e = err as ApiErrorDetails & {
    response?: {
      data?: { detail?: string; error?: string; message?: string };
      status?: number;
    };
    name?: string;
    status?: number;
  };

  if (e?.code === "ECONNABORTED") {
    return "The query timed out. Try a shorter question or lower Top-K.";
  }
  if (e?.code === "CIRCUIT_OPEN") {
    return "API circuit breaker is open. Wait a moment and retry.";
  }
  if (
    e?.name === "AbortError" ||
    e?.name === "CanceledError" ||
    e?.code === "ERR_CANCELED"
  ) {
    return "Request cancelled.";
  }

  const detail =
    e?.response?.data?.detail ||
    e?.response?.data?.error ||
    e?.response?.data?.message ||
    (typeof e?.message === "string"
      ? e.message
      : e?.message && typeof e.message === "object"
        ? (e.message as { detail?: string }).detail
        : undefined);

  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail) return JSON.stringify(detail);
  if (e?.status === 404 || e?.response?.status === 404) {
    return "RAG endpoint not found (404). Deploy /api/v1/rag/query on the backend.";
  }
  return "Could not reach the RAG backend. Check VITE_API_URL and CORS_ORIGINS.";
}

function isCancelled(err: unknown): boolean {
  const e = err as { name?: string; code?: string };
  return (
    e?.name === "AbortError" ||
    e?.name === "CanceledError" ||
    e?.code === "ERR_CANCELED"
  );
}

/** Normalize heterogeneous backend source payloads into Source[] */
export function normalizeSources(raw: unknown): Source[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((s, i) => {
    if (!s || typeof s !== "object") {
      return { n: i + 1, id: `src-${i}`, title: String(s) };
    }
    const o = s as Record<string, unknown>;
    const payload =
      o.payload && typeof o.payload === "object"
        ? (o.payload as Record<string, unknown>)
        : {};

    const similarity =
      typeof o.similarity === "number"
        ? o.similarity
        : typeof o.score === "number"
          ? o.score
          : typeof payload.score === "number"
            ? payload.score
            : undefined;

    const title = String(
      o.title ??
        o.file_name ??
        o.source_file ??
        payload.source_file ??
        payload.doc_id ??
        payload.document_id ??
        `Document ${i + 1}`
    );

    return {
      n:
        typeof o.n === "number"
          ? o.n
          : typeof o.index === "number"
            ? o.index
            : i + 1,
      id: String(o.id ?? o.chunk_id ?? payload.chunk_id ?? `src-${i}`),
      chunk_id:
        String(o.chunk_id ?? payload.chunk_id ?? o.id ?? "") || undefined,
      document_id:
        String(
          o.document_id ?? payload.document_id ?? payload.doc_id ?? ""
        ) || undefined,
      title,
      file_name: (o.file_name ??
        payload.file_name ??
        payload.source_file) as string | undefined,
      source_file: (o.source_file ?? payload.source_file) as
        | string
        | undefined,
      page:
        typeof o.page === "number"
          ? o.page
          : typeof payload.page === "number"
            ? payload.page
            : undefined,
      similarity,
      score: typeof o.score === "number" ? o.score : undefined,
      text: String(o.text ?? payload.text ?? o.content ?? ""),
    };
  });
}

async function callRag(
  query: string,
  topK: number,
  signal: AbortSignal
): Promise<{
  answer?: string;
  result?: string;
  sources?: unknown;
  citations?: unknown;
  confidence_score?: number;
  processing_time_ms?: number;
}> {
  if (typeof apiClient.queryRag === "function") {
    return apiClient.queryRag({ query, top_k: topK }, signal);
  }
  return apiClient.post(
    "/api/v1/rag/query",
    { query, top_k: topK },
    { signal, timeout: 90_000 }
  ) as Promise<{
    answer?: string;
    result?: string;
    sources?: unknown;
    citations?: unknown;
    confidence_score?: number;
    processing_time_ms?: number;
  }>;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch {
      return false;
    }
  }
}

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Hello! I am ready to answer questions about your ingested documents. Ask me anything — answers include citations when the vector store has matching chunks.",
  sources: [],
};

// ---------------------------------------------------------------------------
// Markdown components
// ---------------------------------------------------------------------------

const mdComponents: Components = {
  p: ({ children }) => (
    <p className="mb-2 whitespace-pre-wrap last:mb-0">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-blue-600 underline decoration-blue-300 underline-offset-2 hover:text-blue-700"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-gray-900">{children}</strong>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = Boolean(className?.includes("language-"));
    if (isBlock) {
      return (
        <code
          className={`block overflow-x-auto rounded-lg bg-gray-900/95 p-3 text-[12px] leading-relaxed text-gray-100 ${className ?? ""}`}
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[12px] text-gray-800"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg last:mb-0">{children}</pre>
  ),
  h1: ({ children }) => (
    <h1 className="mb-2 text-base font-semibold text-gray-900">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-1.5 text-sm font-semibold text-gray-900">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1 text-sm font-semibold text-gray-800">{children}</h3>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-blue-200 pl-3 text-gray-600">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="min-w-full border-collapse text-left text-xs">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-gray-200 bg-gray-50 px-2 py-1 font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-gray-200 px-2 py-1">{children}</td>
  ),
};

// ---------------------------------------------------------------------------
// Citation panel
// ---------------------------------------------------------------------------

function CitationPanel({
  source,
  onClose,
}: {
  source: Source;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const title =
    source.title ||
    source.file_name ||
    source.source_file ||
    source.id ||
    "Source";
  const score = source.similarity ?? source.score;

  const handleCopy = async () => {
    const body = [
      title,
      source.page != null ? `Page ${source.page}` : null,
      score != null ? `Relevance ${(Number(score) * 100).toFixed(0)}%` : null,
      "",
      source.text || "(no excerpt)",
    ]
      .filter((x) => x != null)
      .join("\n");
    const ok = await copyText(body);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/30 p-3 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="citation-title"
      onClick={onClose}
    >
      <div
        className="max-h-[min(80vh,520px)] w-full max-w-lg overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-4 py-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
              Citation{source.n != null ? ` [${source.n}]` : ""}
            </p>
            <h3
              id="citation-title"
              className="mt-0.5 truncate text-sm font-semibold text-gray-900"
            >
              {title}
            </h3>
            <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-gray-500">
              {source.page != null ? <span>Page {source.page}</span> : null}
              {score != null ? (
                <span>Relevance {(Number(score) * 100).toFixed(0)}%</span>
              ) : null}
              {source.chunk_id ? (
                <span className="truncate font-mono text-[10px] text-gray-400">
                  {source.chunk_id}
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-72 overflow-y-auto px-4 py-3">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
            {source.text?.trim() || "No excerpt available for this source."}
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-gray-100 px-4 py-3">
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-600" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "Copied" : "Copy excerpt"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({
  msg,
  onOpenSource,
  onRetry,
}: {
  msg: ChatMessage;
  onOpenSource: (s: Source) => void;
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const isUser = msg.role === "user";

  const handleCopy = async () => {
    const ok = await copyText(msg.content);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div
      className={`group flex items-start gap-3 ${
        isUser ? "flex-row-reverse" : ""
      }`}
    >
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? "bg-blue-600 text-white"
            : msg.isError
              ? "border border-red-200 bg-red-50 text-red-600"
              : "border border-gray-200 bg-white text-blue-600 shadow-sm"
        }`}
      >
        {isUser ? (
          <User className="h-5 w-5" />
        ) : msg.isError ? (
          <AlertCircle className="h-5 w-5" />
        ) : (
          <Bot className="h-5 w-5" />
        )}
      </div>

      <div
        className={`relative max-w-[min(100%,28rem)] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm sm:max-w-[75%] ${
          isUser
            ? "rounded-tr-none bg-blue-600 text-white"
            : msg.isError
              ? "rounded-tl-none border border-red-100 bg-red-50 text-red-800"
              : "rounded-tl-none border border-gray-100 bg-white text-gray-800"
        }`}
      >
        {/* Copy — assistant only */}
        {!isUser && msg.content ? (
          <div className="mb-1.5 flex justify-end sm:absolute sm:-right-1 sm:-top-1 sm:mb-0">
            <button
              type="button"
              onClick={() => void handleCopy()}
              className={`inline-flex h-7 items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 text-[11px] font-medium text-gray-500 shadow-sm transition hover:text-gray-800 sm:h-7 sm:w-7 sm:justify-center sm:px-0 ${
                copied
                  ? "text-emerald-600"
                  : "sm:opacity-0 sm:group-hover:opacity-100"
              }`}
              title={copied ? "Copied" : "Copy answer"}
              aria-label={copied ? "Copied" : "Copy answer"}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              <span className="sm:hidden">{copied ? "Copied" : "Copy"}</span>
            </button>
          </div>
        ) : null}

        {/* Body */}
        {isUser || msg.isError ? (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        ) : (
          <div className="rag-md max-w-none text-gray-800">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={mdComponents}
            >
              {msg.content}
            </ReactMarkdown>
          </div>
        )}

        {(msg.confidence != null || msg.latencyMs != null) &&
          !msg.isError &&
          !isUser && (
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-gray-400">
              {msg.confidence != null && (
                <span>
                  Confidence {(Number(msg.confidence) * 100).toFixed(0)}%
                </span>
              )}
              {msg.latencyMs != null && <span>{msg.latencyMs} ms</span>}
            </div>
          )}

        {msg.isError && onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry
          </button>
        ) : null}

        {msg.sources && msg.sources.length > 0 ? (
          <div className="mt-3 border-t border-gray-100 pt-3">
            <p className="mb-1.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              <Quote className="h-3 w-3" />
              Sources &amp; citations
            </p>
            <div className="flex flex-col gap-1.5">
              {msg.sources.map((source, sIdx) => {
                const label =
                  source.title ||
                  source.file_name ||
                  source.source_file ||
                  source.id ||
                  `Document ${sIdx + 1}`;
                const score = source.similarity ?? source.score;
                return (
                  <button
                    key={source.id || sIdx}
                    type="button"
                    onClick={() => onOpenSource(source)}
                    className="rounded-md border border-gray-200/80 bg-gray-50 px-2.5 py-1.5 text-left text-xs text-gray-700 transition hover:border-blue-200 hover:bg-blue-50/60"
                  >
                    <span className="inline-flex items-center gap-1.5 font-medium">
                      <FileText className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                      {source.n != null ? (
                        <span className="rounded bg-blue-100 px-1 py-0.5 text-[10px] font-semibold text-blue-700">
                          [{source.n}]
                        </span>
                      ) : null}
                      <span className="max-w-[200px] truncate sm:max-w-[240px]">
                        {label}
                      </span>
                      {source.page != null ? (
                        <span className="font-normal text-gray-400">
                          (p. {source.page})
                        </span>
                      ) : null}
                      {score != null ? (
                        <span className="font-normal text-gray-400">
                          · {(Number(score) * 100).toFixed(0)}%
                        </span>
                      ) : null}
                    </span>
                    {source.text ? (
                      <span className="mt-1 line-clamp-2 block pl-5 text-gray-500">
                        {String(source.text)}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RAGChat
// ---------------------------------------------------------------------------

export default function RAGChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([{ ...WELCOME }]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [activeSource, setActiveSource] = useState<Source | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const formHintId = useId();

  const onlyWelcome = messages.length === 1 && messages[0]?.id === "welcome";

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
  }, []);

  const clearChat = () => {
    stop();
    setMessages([{ ...WELCOME, id: newId() }]);
    setInput("");
    setActiveSource(null);
    inputRef.current?.focus();
  };

  const runQuery = async (userMessage: string) => {
    const q = userMessage.trim();
    if (!q || loading) return;

    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", content: q },
    ]);
    setLoading(true);
    setActiveSource(null);

    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = performance.now();

    try {
      const data = await callRag(q, topK, controller.signal);

      const answer =
        data.answer ||
        data.result ||
        "No response generated from the documents.";
      const sources = normalizeSources(data.sources ?? data.citations);
      const latencyMs =
        typeof data.processing_time_ms === "number"
          ? data.processing_time_ms
          : Math.round(performance.now() - t0);

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          content: answer,
          sources,
          confidence: data.confidence_score,
          latencyMs,
          prompt: q,
        },
      ]);
    } catch (err) {
      const cancelled = isCancelled(err);
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          content: cancelled ? "Request cancelled." : errorMessage(err),
          sources: [],
          isError: !cancelled,
          prompt: q,
        },
      ]);
      if (!cancelled) console.error(err);
    } finally {
      abortRef.current = null;
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const userMessage = input.trim();
    if (!userMessage || loading) return;
    setInput("");
    await runQuery(userMessage);
  };

  const onSuggestion = (text: string) => {
    if (loading) return;
    setInput("");
    void runQuery(text);
  };

  const nearLimit = input.length >= MAX_INPUT * 0.9;

  const headerBadge = useMemo(
    () => (
      <span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
        RAG Active
      </span>
    ),
    []
  );

  return (
    <div className="mx-auto flex h-[min(720px,75vh)] min-h-[560px] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-gray-100 bg-white shadow-md">
      {/* Header */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-gray-100 bg-gray-50 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-blue-600" />
          <h2 className="font-semibold text-gray-800">
            Document Intelligence Assistant
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            Top-K
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) =>
                setTopK(
                  Math.min(20, Math.max(1, Number(e.target.value) || 5))
                )
              }
              className="w-14 rounded-md border border-gray-200 bg-white px-1.5 py-1 text-xs"
              disabled={loading}
            />
          </label>
          <button
            type="button"
            onClick={clearChat}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            title="Clear chat"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </button>
          {headerBadge}
        </div>
      </div>

      {/* Messages */}
      <div className="min-h-[320px] flex-1 space-y-6 overflow-y-auto bg-slate-50/80 p-4 sm:p-6">
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            onOpenSource={setActiveSource}
            onRetry={
              msg.isError && msg.prompt
                ? () => void runQuery(msg.prompt!)
                : undefined
            }
          />
        ))}

        {onlyWelcome && !loading ? (
          <div className="space-y-2 pl-12">
            <p className="flex items-center gap-1.5 text-xs text-gray-400">
              <MessageSquare className="h-3.5 w-3.5" />
              Try a sample question
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onSuggestion(s)}
                  className="max-w-full rounded-xl border border-blue-100 bg-white px-3 py-2 text-left text-xs text-blue-700 transition-colors hover:border-blue-200 hover:bg-blue-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full border border-gray-200 bg-white text-blue-600 shadow-sm">
              <Bot className="h-5 w-5" />
            </div>
            <div className="flex flex-wrap items-center gap-2 rounded-2xl rounded-tl-none border border-gray-100 bg-white px-4 py-3 text-sm text-gray-500 shadow-sm">
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              <span>Searching vectors &amp; synthesizing answer…</span>
              <button
                type="button"
                onClick={stop}
                className="ml-1 inline-flex items-center gap-1 rounded-lg border border-red-100 bg-red-50 px-2 py-1 text-xs text-red-700 hover:bg-red-100"
              >
                <Square className="h-3 w-3 fill-current" />
                Stop
              </button>
            </div>
          </div>
        ) : null}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => void handleSend(e)}
        className="shrink-0 border-t border-gray-100 bg-white p-3 sm:p-4"
      >
        <div className="flex items-end gap-2 sm:gap-3">
          <label htmlFor="rag-chat-input" className="sr-only">
            Message
          </label>
          <textarea
            id="rag-chat-input"
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT))}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Ask a question about your uploaded documents…"
            className="max-h-32 min-h-[42px] flex-1 resize-none rounded-xl border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm transition-all focus:border-blue-500 focus:bg-white focus:outline-none disabled:opacity-60"
            disabled={loading}
            maxLength={MAX_INPUT}
            autoComplete="off"
            aria-describedby={formHintId}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-50 sm:px-5"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <span className="hidden sm:inline">Send</span>
                <Send className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
        <p
          id={formHintId}
          className="mt-1.5 flex flex-wrap items-center justify-between gap-2 px-0.5 text-[11px] text-gray-400"
        >
          <span>Enter to send · Shift+Enter for new line</span>
          {nearLimit ? (
            <span className="tabular-nums text-amber-600">
              {input.length}/{MAX_INPUT}
            </span>
          ) : null}
        </p>
      </form>

      {activeSource ? (
        <CitationPanel
          source={activeSource}
          onClose={() => setActiveSource(null)}
        />
      ) : null}
    </div>
  );
}