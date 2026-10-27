/**
 * ChatInterface — orchestration shell for RAG chat.
 * Responsive toolbar, empty-state suggestions, persistence, export.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ComponentType } from "react";
import {
  Eraser,
  RotateCcw,
  Download,
  MessageSquarePlus,
  Copy,
  Check,
  FileJson,
  Pin,
  MoreHorizontal,
  Sparkles,
} from "lucide-react";
import ChatWindow from "./ChatWindow";
import type { ChatMessage, Citation, RagQueryResult } from "./types";

type ChatWindowProps = {
  messages: ChatMessage[];
  onSend: (text: string) => Promise<void>;
  onStop: () => void;
  isLoading: boolean;
};

const ChatWindowComponent =
  ChatWindow as unknown as ComponentType<ChatWindowProps>;

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

export type RagQueryFn = (
  query: string,
  signal?: AbortSignal
) => Promise<RagQueryResult>;

export interface ChatInterfaceProps {
  queryFn?: RagQueryFn;
  initialMessages?: ChatMessage[];
  maxMessages?: number;
  showToolbar?: boolean;
  suggestions?: string[];
  storageKey?: string;
  title?: string;
  subtitle?: string;
  className?: string;
  onResponse?: (message: ChatMessage, result: RagQueryResult) => void;
  onError?: (error: string, query: string) => void;
  onClear?: () => void;
  onMessagesChange?: (messages: ChatMessage[]) => void;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Defaults                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

const DEFAULT_SUGGESTIONS = [
  "What is our MFA policy for production access?",
  "How should a Severity-1 incident be escalated?",
  "Summarize the data retention requirements",
  "What files are blocked by the security scanner?",
];

const DEFAULT_MAX_MESSAGES = 100;
const DEFAULT_STORAGE_KEY = "doc-intel.rag-chat.v1";

/* ────────────────────────────────────────────────────────────────────────── */
/* Helpers                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function mapSources(sources: RagQueryResult["sources"]): Citation[] {
  return (sources || []).map((s, i) => ({
    id: s.id || `cite-${i + 1}`,
    n: s.n || i + 1,
    documentId: s.documentId,
    fileName: s.fileName,
    title: s.title,
    page: s.page,
    score: s.score,
    text: s.text,
  }));
}

function deriveConfidence(
  result: RagQueryResult
): ChatMessage["confidence"] {
  if (
    result.confidence === "high" ||
    result.confidence === "medium" ||
    result.confidence === "low"
  ) {
    return result.confidence;
  }
  const score = result.confidenceScore;
  if (score == null) return undefined;
  if (score >= 0.75) return "high";
  if (score >= 0.55) return "medium";
  return "low";
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object") {
    if ("name" in err && (err as { name: string }).name === "AbortError") {
      return "Request cancelled.";
    }
    if ("message" in err) {
      return String((err as { message: unknown }).message);
    }
  }
  return "Request failed. Please try again.";
}

function trimMessages(list: ChatMessage[], max: number): ChatMessage[] {
  if (list.length <= max) return list;
  return list.slice(list.length - max);
}

function loadStoredMessages(key: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m): m is ChatMessage =>
        m != null &&
        typeof m === "object" &&
        typeof (m as ChatMessage).id === "string" &&
        typeof (m as ChatMessage).role === "string" &&
        typeof (m as ChatMessage).content === "string"
    );
  } catch {
    return [];
  }
}

function saveStoredMessages(key: string, messages: ChatMessage[]): void {
  try {
    const stable = messages.filter((m) => !m.isStreaming);
    localStorage.setItem(key, JSON.stringify(stable));
  } catch {
    /* quota / private mode */
  }
}

function downloadText(filename: string, content: string, mime: string): void {
  try {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Download failed:", err);
  }
}

function exportTranscriptTxt(messages: ChatMessage[]): void {
  const lines = messages.map((m) => {
    const role = m.role.toUpperCase();
    const time = new Date(m.createdAt).toISOString();
    const body = m.error || m.content || "";
    const cites =
      m.citations && m.citations.length
        ? `\nCitations: ${m.citations
            .map((c) => `[${c.n}] ${c.fileName || c.title || c.id}`)
            .join("; ")}`
        : "";
    return `[${time}] ${role}:\n${body}${cites}`;
  });

  downloadText(
    `rag-chat-${new Date().toISOString().slice(0, 10)}.txt`,
    lines.join("\n\n---\n\n"),
    "text/plain;charset=utf-8"
  );
}

function exportTranscriptJson(messages: ChatMessage[]): void {
  downloadText(
    `rag-chat-${new Date().toISOString().slice(0, 10)}.json`,
    JSON.stringify(
      { exported_at: new Date().toISOString(), messages },
      null,
      2
    ),
    "application/json"
  );
}

function formatThreadForClipboard(messages: ChatMessage[]): string {
  return messages
    .map((m) => {
      const role = m.role === "user" ? "You" : "Assistant";
      const body = m.error || m.content || "";
      const cites =
        m.citations && m.citations.length
          ? `\nSources: ${m.citations
              .map((c) => `[${c.n}] ${c.fileName || c.title || c.id}`)
              .join("; ")}`
          : "";
      return `${role}: ${body}${cites}`;
    })
    .join("\n\n");
}

async function mockRagQuery(
  query: string,
  signal?: AbortSignal
): Promise<RagQueryResult> {
  await new Promise<void>((resolve, reject) => {
    const t = window.setTimeout(resolve, 900);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

  const lower = query.toLowerCase();
  const refuse =
    lower.includes("weather") ||
    lower.includes("stock price") ||
    lower.includes("who won");

  if (refuse) {
    return {
      answer:
        "I could not find this in the approved indexed documents. Try rephrasing, or upload the relevant policy to the library.",
      sources: [],
      confidence: "low",
      confidenceScore: 0.12,
      refused: true,
    };
  }

  return {
    answer: `Based on indexed policy documents, here is a grounded response to: “${query}”.\n\nRefer to the cited sources for the approved wording.`,
    sources: [
      {
        id: "c1",
        n: 1,
        fileName: "security_policy.pdf",
        page: 4,
        score: 0.87,
        text: "Access to production systems requires MFA and least-privilege roles…",
      },
      {
        id: "c2",
        n: 2,
        fileName: "incident_runbook.md",
        page: 1,
        score: 0.79,
        text: "Severity-1 incidents must be escalated within 15 minutes…",
      },
    ],
    confidence: "high",
    confidenceScore: 0.84,
    refused: false,
  };
}

/* ────────────────────────────────────────────────────────────────────────── */
/* UI atoms                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

function ToolBtn({
  label,
  onClick,
  disabled,
  active,
  danger,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={[
        "inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 sm:px-3",
        "text-xs font-medium transition-all duration-150",
        "disabled:cursor-not-allowed disabled:opacity-40",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40",
        active
          ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
          : danger
            ? "border-white/10 bg-white/[0.04] text-slate-300 hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-200"
            : "border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/20 hover:bg-white/[0.07] hover:text-white",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function Chip({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "slate" | "indigo" | "emerald";
}) {
  const tones = {
    slate: "bg-white/[0.04] text-slate-400 border-white/10",
    indigo: "bg-indigo-500/15 text-indigo-300 border-indigo-400/25",
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-400/20",
  };
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
      ].join(" ")}
    >
      {children}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Component                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

const ChatInterface = ({
  queryFn,
  initialMessages,
  maxMessages = DEFAULT_MAX_MESSAGES,
  showToolbar = true,
  suggestions = DEFAULT_SUGGESTIONS,
  storageKey = DEFAULT_STORAGE_KEY,
  title = "Document chat",
  subtitle = "Answers are grounded in your indexed library",
  className = "",
  onResponse,
  onError,
  onClear,
  onMessagesChange,
}: ChatInterfaceProps) => {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    if (initialMessages && initialMessages.length) return initialMessages;
    if (storageKey) return loadStoredMessages(storageKey);
    return [];
  });
  const [isLoading, setIsLoading] = useState(false);
  const [lastUserText, setLastUserText] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pinnedSuggestions, setPinnedSuggestions] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const hydratedRef = useRef(false);
  const runQuery = queryFn ?? mockRagQuery;

  useEffect(() => {
    if (initialMessages && initialMessages.length) {
      setMessages(initialMessages);
    }
  }, [initialMessages]);

  useEffect(() => {
    if (!hydratedRef.current) {
      hydratedRef.current = true;
      return;
    }
    if (storageKey) saveStoredMessages(storageKey, messages);
    onMessagesChange?.(messages);
  }, [messages, storageKey, onMessagesChange]);

  const cancelInFlight = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const handleStop = useCallback(() => {
    cancelInFlight();
    setIsLoading(false);
    setMessages((prev) =>
      prev.map((m) =>
        m.isStreaming
          ? {
              ...m,
              isStreaming: false,
              content: m.content || "Generation stopped.",
            }
          : m
      )
    );
  }, [cancelInFlight]);

  const handleClear = useCallback(() => {
    if (isLoading) handleStop();
    setMessages([]);
    setLastUserText(null);
    setPinnedSuggestions(true);
    if (storageKey) {
      try {
        localStorage.removeItem(storageKey);
      } catch {
        /* ignore */
      }
    }
    onClear?.();
  }, [isLoading, handleStop, storageKey, onClear]);

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return;

      cancelInFlight();
      const controller = new AbortController();
      abortRef.current = controller;

      setLastUserText(trimmed);
      setPinnedSuggestions(false);

      const userMsg: ChatMessage = {
        id: createId("user"),
        role: "user",
        content: trimmed,
        createdAt: new Date().toISOString(),
      };

      const placeholderId = createId("asst");
      const placeholder: ChatMessage = {
        id: placeholderId,
        role: "assistant",
        content: "",
        createdAt: new Date().toISOString(),
        isStreaming: true,
      };

      setMessages((prev) =>
        trimMessages([...prev, userMsg, placeholder], maxMessages)
      );
      setIsLoading(true);

      try {
        const result = await runQuery(trimmed, controller.signal);
        if (controller.signal.aborted) return;

        const assistantMsg: ChatMessage = {
          id: placeholderId,
          role: "assistant",
          content: result.answer,
          createdAt: new Date().toISOString(),
          citations: mapSources(result.sources),
          confidence: deriveConfidence(result),
          confidenceScore: result.confidenceScore,
          refused: Boolean(result.refused),
          isStreaming: false,
        };

        setMessages((prev) =>
          prev.map((m) => (m.id === placeholderId ? assistantMsg : m))
        );
        onResponse?.(assistantMsg, result);
      } catch (err) {
        if (controller.signal.aborted) return;

        const msg = errorMessage(err);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === placeholderId
              ? {
                  ...m,
                  content: "",
                  error: msg,
                  isStreaming: false,
                }
              : m
          )
        );
        onError?.(msg, trimmed);
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [isLoading, cancelInFlight, runQuery, maxMessages, onResponse, onError]
  );

  const handleRetry = useCallback(() => {
    if (!lastUserText || isLoading) return;

    setMessages((prev) => {
      const next = [...prev];
      while (
        next.length &&
        next[next.length - 1].role === "assistant" &&
        (next[next.length - 1].error || !next[next.length - 1].content)
      ) {
        next.pop();
      }
      if (
        next.length &&
        next[next.length - 1].role === "user" &&
        next[next.length - 1].content === lastUserText
      ) {
        next.pop();
      }
      return next;
    });
    void handleSend(lastUserText);
  }, [lastUserText, isLoading, handleSend]);

  const handleCopyThread = useCallback(async () => {
    if (!messages.length) return;
    try {
      await navigator.clipboard.writeText(formatThreadForClipboard(messages));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  }, [messages]);

  const canRetry = useMemo(() => {
    if (!lastUserText || isLoading) return false;
    const last = messages[messages.length - 1];
    return Boolean(last && last.role === "assistant" && last.error);
  }, [lastUserText, isLoading, messages]);

  const isEmpty = messages.length === 0 && !isLoading;
  const showSuggestions =
    isEmpty && pinnedSuggestions && suggestions.length > 0;

  const citationCount = useMemo(
    () => messages.reduce((n, m) => n + (m.citations?.length ?? 0), 0),
    [messages]
  );

  const hasMessages = messages.length > 0;

  return (
    <div
      className={[
        "flex h-full min-h-[28rem] flex-col overflow-hidden rounded-2xl",
        "border border-white/10 bg-slate-950/60 shadow-2xl shadow-black/20",
        className,
      ].join(" ")}
    >
      {/* Toolbar */}
      {showToolbar && (
        <div className="shrink-0 border-b border-white/10 bg-slate-950/80 px-3 py-3 sm:px-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-blue-400/20 bg-blue-500/10">
                  <MessageSquarePlus className="h-4 w-4 text-blue-300" />
                </span>
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-semibold text-slate-100 sm:text-base">
                    {title}
                  </h2>
                  <p className="truncate text-xs text-slate-500">{subtitle}</p>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {hasMessages ? (
                  <Chip>
                    <span className="tabular-nums">{messages.length}</span>{" "}
                    messages
                  </Chip>
                ) : null}
                {citationCount > 0 ? (
                  <Chip tone="indigo">
                    <span className="tabular-nums">{citationCount}</span>{" "}
                    citations
                  </Chip>
                ) : null}
                {storageKey ? (
                  <Chip tone="emerald">
                    <Pin size={10} aria-hidden="true" />
                    Saved locally
                  </Chip>
                ) : null}
                {isLoading ? (
                  <Chip tone="indigo">
                    <Sparkles size={10} className="animate-pulse" />
                    Generating
                  </Chip>
                ) : null}
              </div>
            </div>

            {/* Desktop actions */}
            <div className="hidden flex-wrap items-center justify-end gap-1.5 sm:flex">
              <ToolBtn
                label="Retry last failed question"
                onClick={handleRetry}
                disabled={!canRetry}
              >
                <RotateCcw size={14} aria-hidden="true" />
                <span className="hidden md:inline">Retry</span>
              </ToolBtn>

              <ToolBtn
                label="Copy thread"
                onClick={handleCopyThread}
                disabled={!hasMessages}
                active={copied}
              >
                {copied ? (
                  <Check size={14} className="text-emerald-400" />
                ) : (
                  <Copy size={14} />
                )}
                <span className="hidden md:inline">
                  {copied ? "Copied" : "Copy"}
                </span>
              </ToolBtn>

              <ToolBtn
                label="Export as text"
                onClick={() => exportTranscriptTxt(messages)}
                disabled={!hasMessages}
              >
                <Download size={14} />
                <span className="hidden lg:inline">TXT</span>
              </ToolBtn>

              <ToolBtn
                label="Export as JSON"
                onClick={() => exportTranscriptJson(messages)}
                disabled={!hasMessages}
              >
                <FileJson size={14} />
                <span className="hidden lg:inline">JSON</span>
              </ToolBtn>

              <ToolBtn
                label="Clear conversation"
                onClick={handleClear}
                disabled={!hasMessages && !isLoading}
                danger
              >
                <Eraser size={14} />
                <span className="hidden md:inline">Clear</span>
              </ToolBtn>
            </div>

            {/* Mobile overflow */}
            <div className="relative sm:hidden">
              <ToolBtn
                label="More actions"
                onClick={() => setMenuOpen((v) => !v)}
              >
                <MoreHorizontal size={16} />
              </ToolBtn>

              {menuOpen ? (
                <>
                  <button
                    type="button"
                    className="fixed inset-0 z-30"
                    aria-label="Close menu"
                    onClick={() => setMenuOpen(false)}
                  />
                  <div className="absolute right-0 z-40 mt-2 w-44 overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 p-1 shadow-2xl backdrop-blur-xl">
                    {(
                      [
                        {
                          label: "Retry",
                          icon: <RotateCcw size={14} />,
                          onClick: handleRetry,
                          disabled: !canRetry,
                        },
                        {
                          label: copied ? "Copied" : "Copy",
                          icon: copied ? (
                            <Check size={14} className="text-emerald-400" />
                          ) : (
                            <Copy size={14} />
                          ),
                          onClick: handleCopyThread,
                          disabled: !hasMessages,
                        },
                        {
                          label: "Export TXT",
                          icon: <Download size={14} />,
                          onClick: () => exportTranscriptTxt(messages),
                          disabled: !hasMessages,
                        },
                        {
                          label: "Export JSON",
                          icon: <FileJson size={14} />,
                          onClick: () => exportTranscriptJson(messages),
                          disabled: !hasMessages,
                        },
                        {
                          label: "Clear",
                          icon: <Eraser size={14} />,
                          onClick: handleClear,
                          disabled: !hasMessages && !isLoading,
                          danger: true,
                        },
                      ] as const
                    ).map((item) => (
                      <button
                        key={item.label}
                        type="button"
                        disabled={item.disabled}
                        onClick={() => {
                          item.onClick();
                          setMenuOpen(false);
                        }}
                        className={[
                          "flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition",
                          "disabled:opacity-40",
                          "danger" in item && item.danger
                            ? "text-rose-300 hover:bg-rose-500/10"
                            : "text-slate-200 hover:bg-white/5",
                        ].join(" ")}
                      >
                        {item.icon}
                        {item.label}
                      </button>
                    ))}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {/* Empty-state suggestions */}
      {showSuggestions ? (
        <div className="shrink-0 border-b border-white/5 px-3 py-4 sm:px-5">
          <div className="mx-auto max-w-3xl">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-blue-300" />
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                Suggested questions
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void handleSend(s)}
                  className={[
                    "rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3",
                    "text-left text-sm text-slate-300 transition",
                    "hover:border-blue-400/30 hover:bg-blue-500/10 hover:text-slate-100",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40",
                  ].join(" ")}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* Chat surface */}
      <div className="min-h-0 flex-1">
        <ChatWindowComponent
          messages={messages}
          onSend={handleSend}
          onStop={handleStop}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
};

export default ChatInterface;