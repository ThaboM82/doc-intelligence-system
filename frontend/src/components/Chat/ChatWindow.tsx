/**
 * ChatWindow — RAG message list + composer.
 * Mobile: swipe left on a message for Copy / Retry / Sources.
 * Citation details open in CitationPanel.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Send,
  Square,
  Bot,
  User,
  AlertCircle,
  Loader2,
  Copy,
  RotateCcw,
  Quote,
} from "lucide-react";
import CitationPanel from "./CitationPanel";
import type { ChatMessage, Citation } from "./types";

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export type ChatWindowProps = {
  messages: ChatMessage[];
  onSend: (text: string) => Promise<void>;
  onStop: () => void;
  isLoading: boolean;
  /** Retry last failed assistant turn (parent-owned) */
  onRetryLast?: () => void;
  /** Optional side-effect when sources are requested */
  onOpenCitations?: (message: ChatMessage) => void;
  placeholder?: string;
  className?: string;
};

// ---------------------------------------------------------------------------
// Swipe hook (local — no extra file required)
// ---------------------------------------------------------------------------

function useSwipeGesture({
  threshold = 40,
  maxReveal = 128,
  directionLockRatio = 1.25,
  disabled = false,
  onOpenChange,
}: {
  threshold?: number;
  maxReveal?: number;
  directionLockRatio?: number;
  disabled?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const startX = useRef(0);
  const startY = useRef(0);
  const dragging = useRef(false);
  const locked = useRef<"h" | "v" | null>(null);

  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(false);

  const close = useCallback(() => {
    setOffset(0);
    setOpen(false);
    onOpenChange?.(false);
  }, [onOpenChange]);

  const openTray = useCallback(() => {
    setOffset(-maxReveal);
    setOpen(true);
    onOpenChange?.(true);
  }, [maxReveal, onOpenChange]);

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (disabled) return;
      const t = e.touches[0];
      startX.current = t.clientX;
      startY.current = t.clientY;
      dragging.current = true;
      locked.current = null;
    },
    [disabled]
  );

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (disabled || !dragging.current) return;
      const t = e.touches[0];
      const dx = t.clientX - startX.current;
      const dy = t.clientY - startY.current;

      if (!locked.current) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        locked.current =
          Math.abs(dx) > Math.abs(dy) * directionLockRatio ? "h" : "v";
      }
      if (locked.current === "v") return;

      e.preventDefault();
      const base = open ? -maxReveal : 0;
      setOffset(Math.min(0, Math.max(-maxReveal, base + dx)));
    },
    [disabled, directionLockRatio, maxReveal, open]
  );

  const onTouchEnd = useCallback(() => {
    if (disabled || !dragging.current) return;
    dragging.current = false;
    if (locked.current !== "h") {
      locked.current = null;
      return;
    }
    locked.current = null;
    if (offset <= -threshold) openTray();
    else close();
  }, [disabled, offset, threshold, openTray, close]);

  return {
    offset,
    open,
    close,
    handlers: {
      onTouchStart,
      onTouchMove,
      onTouchEnd,
      onTouchCancel: onTouchEnd,
    },
  };
}

// ---------------------------------------------------------------------------
// Swipeable row
// ---------------------------------------------------------------------------

function SwipeableMessage({
  message,
  isActive,
  onActivate,
  onCopy,
  onRetry,
  onCite,
  children,
}: {
  message: ChatMessage;
  isActive: boolean;
  onActivate: () => void;
  onCopy: (m: ChatMessage) => void;
  onRetry?: (m: ChatMessage) => void;
  onCite?: (m: ChatMessage) => void;
  children: ReactNode;
}) {
  const canRetry =
    message.role === "assistant" && Boolean(message.error) && Boolean(onRetry);
  const canCite =
    message.role === "assistant" &&
    Boolean(message.citations?.length) &&
    Boolean(onCite);

  const actionCount = 1 + (canRetry ? 1 : 0) + (canCite ? 1 : 0);
  const maxReveal = Math.min(168, actionCount * 56);

  const { offset, open, close, handlers } = useSwipeGesture({
    maxReveal,
    threshold: 40,
    onOpenChange: (v) => {
      if (v) onActivate();
    },
  });

  useEffect(() => {
    if (!isActive && open) close();
  }, [isActive, open, close]);

  const run = (fn?: (m: ChatMessage) => void) => {
    fn?.(message);
    close();
  };

  return (
    <div className="relative w-full overflow-hidden">
      <div
        className="absolute inset-y-0 right-0 flex items-stretch"
        style={{ width: maxReveal }}
        aria-hidden={!open}
      >
        <button
          type="button"
          onClick={() => run(onCopy)}
          className="flex w-14 flex-col items-center justify-center gap-1 bg-blue-600 text-[10px] font-medium text-white active:bg-blue-500"
        >
          <Copy className="h-4 w-4" />
          Copy
        </button>
        {canRetry ? (
          <button
            type="button"
            onClick={() => run(onRetry)}
            className="flex w-14 flex-col items-center justify-center gap-1 bg-amber-600 text-[10px] font-medium text-white active:bg-amber-500"
          >
            <RotateCcw className="h-4 w-4" />
            Retry
          </button>
        ) : null}
        {canCite ? (
          <button
            type="button"
            onClick={() => run(onCite)}
            className="flex w-14 flex-col items-center justify-center gap-1 bg-violet-600 text-[10px] font-medium text-white active:bg-violet-500"
          >
            <Quote className="h-4 w-4" />
            Sources
          </button>
        ) : null}
      </div>

      <div
        className="relative touch-pan-y will-change-transform"
        style={{
          transform: `translate3d(${offset}px, 0, 0)`,
          transition:
            open || offset === 0 ? "transform 180ms ease-out" : "none",
        }}
        {...handlers}
      >
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bubble
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function MessageBubble({
  message,
  onCitationClick,
}: {
  message: ChatMessage;
  onCitationClick?: (c: Citation) => void;
}) {
  const isUser = message.role === "user";
  const body = message.error || message.content || "";
  const streaming = Boolean(message.isStreaming);

  return (
    <div
      className={[
        "flex w-full gap-2 px-1 sm:gap-3",
        isUser ? "flex-row-reverse" : "flex-row",
      ].join(" ")}
    >
      <div
        className={[
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border",
          isUser
            ? "border-blue-400/25 bg-blue-500/15 text-blue-300"
            : "border-white/10 bg-white/5 text-slate-300",
        ].join(" ")}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div
        className={[
          "max-w-[min(100%,28rem)] rounded-2xl border px-3.5 py-2.5 shadow-sm sm:max-w-xl",
          isUser
            ? "border-blue-400/20 bg-blue-600/20 text-slate-50"
            : message.error
              ? "border-rose-400/25 bg-rose-500/10 text-rose-50"
              : "border-white/10 bg-slate-900/90 text-slate-100",
        ].join(" ")}
      >
        {message.error ? (
          <div className="flex items-start gap-2 text-sm leading-relaxed">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
            <p>{message.error}</p>
          </div>
        ) : streaming && !body ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Thinking…
          </div>
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{body}</p>
        )}

        {message.citations && message.citations.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-white/5 pt-2">
            {message.citations.map((c) => (
              <button
                key={c.id || `${c.n}-${c.fileName}`}
                type="button"
                onClick={() => onCitationClick?.(c)}
                className="rounded-md border border-violet-400/20 bg-violet-500/10 px-1.5 py-0.5 text-left text-[10px] text-violet-200 transition hover:bg-violet-500/20"
              >
                [{c.n}] {c.fileName || c.title || c.id}
              </button>
            ))}
          </div>
        ) : null}

        <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-slate-500">
          <span>{formatTime(message.createdAt)}</span>
          {message.confidence ? (
            <span className="capitalize">{message.confidence} confidence</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChatWindow
// ---------------------------------------------------------------------------

export default function ChatWindow({
  messages,
  onSend,
  onStop,
  isLoading,
  onRetryLast,
  onOpenCitations,
  placeholder = "Ask about your documents…",
  className = "",
}: ChatWindowProps) {
  const [text, setText] = useState("");
  const [activeSwipeId, setActiveSwipeId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isLoading]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => setActiveSwipeId(null);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-grow composer
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [text]);

  const submit = async () => {
    const value = text.trim();
    if (!value || isLoading) return;
    setText("");
    setActiveSwipeId(null);
    await onSend(value);
  };

  const copyMessage = async (m: ChatMessage) => {
    const value = m.error || m.content || "";
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* ignore */
    }
  };

  const openSources = (m: ChatMessage) => {
    const first = m.citations?.[0] ?? null;
    if (first) setActiveCitation(first);
    onOpenCitations?.(m);
  };

  return (
    <div className={["flex h-full min-h-0 flex-col", className].join(" ")}>
      {/* Messages */}
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-2 py-3 sm:px-4"
      >
        {messages.length === 0 ? (
          <div className="flex h-full min-h-[12rem] flex-col items-center justify-center px-4 text-center">
            <p className="text-sm font-medium text-slate-300">
              Start a conversation
            </p>
            <p className="mt-1 max-w-sm text-xs text-slate-500">
              Ask a question grounded in your indexed documents. On mobile,
              swipe a message left for Copy, Retry, or Sources.
            </p>
          </div>
        ) : (
          <ul className="mx-auto flex w-full max-w-3xl flex-col gap-3">
            {messages.map((m) => (
              <li key={m.id}>
                <SwipeableMessage
                  message={m}
                  isActive={activeSwipeId === m.id}
                  onActivate={() => setActiveSwipeId(m.id)}
                  onCopy={copyMessage}
                  onRetry={
                    m.role === "assistant" && m.error && onRetryLast
                      ? () => onRetryLast()
                      : undefined
                  }
                  onCite={
                    m.citations?.length ? () => openSources(m) : undefined
                  }
                >
                  <MessageBubble
                    message={m}
                    onCitationClick={(c) => setActiveCitation(c)}
                  />
                </SwipeableMessage>
              </li>
            ))}
          </ul>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-white/10 bg-slate-950/90 p-2 sm:p-3">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
          <label className="sr-only" htmlFor="chat-input">
            Message
          </label>
          <textarea
            id="chat-input"
            ref={textareaRef}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            placeholder={placeholder}
            disabled={isLoading}
            className={[
              "max-h-32 min-h-[44px] flex-1 resize-none rounded-2xl border border-white/10",
              "bg-white/[0.04] px-3.5 py-3 text-sm text-slate-100 placeholder:text-slate-500",
              "outline-none focus:border-blue-400/40 focus:ring-2 focus:ring-blue-500/20",
              "disabled:opacity-60",
            ].join(" ")}
          />

          {isLoading ? (
            <button
              type="button"
              onClick={onStop}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-rose-400/30 bg-rose-500/15 text-rose-200 transition hover:bg-rose-500/25"
              title="Stop"
              aria-label="Stop generating"
            >
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={!text.trim()}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-blue-400/30 bg-blue-500/20 text-blue-100 transition hover:bg-blue-500/30 disabled:opacity-40"
              title="Send"
              aria-label="Send message"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mx-auto mt-1.5 hidden max-w-3xl text-[10px] text-slate-600 sm:block">
          Enter to send · Shift+Enter for newline · Swipe left on a message for
          actions
        </p>
      </div>

      <CitationPanel
        open={Boolean(activeCitation)}
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  );
}