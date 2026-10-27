
/**
 * MessageList — scrollable RAG chat messages with swipe actions.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Bot,
  User,
  AlertCircle,
  Loader2,
  Copy,
  RotateCcw,
  Quote,
  Check,
} from "lucide-react";
import type { ChatMessage, Citation } from "./types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export type MessageListProps = {
  messages: ChatMessage[];
  isLoading?: boolean;
  /** Copy message body */
  onCopy?: (message: ChatMessage) => void;
  /** Retry last failed assistant turn */
  onRetry?: (message: ChatMessage) => void;
  /** Open sources / first citation */
  onCite?: (message: ChatMessage) => void;
  /** Click a citation chip */
  onCitationClick?: (citation: Citation, message: ChatMessage) => void;
  emptyTitle?: string;
  emptyDescription?: string;
  className?: string;
};

// ---------------------------------------------------------------------------
// Swipe (local)
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

function SwipeableRow({
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
  onCopy?: (m: ChatMessage) => void;
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

function formatTime(iso?: string): string {
  if (!iso) return "";
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
  onCopyDesktop,
}: {
  message: ChatMessage;
  onCitationClick?: (c: Citation) => void;
  onCopyDesktop?: () => void;
}) {
  const isUser = message.role === "user";
  const body = message.error || message.content || "";
  const streaming = Boolean(message.isStreaming);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (onCopyDesktop) {
      onCopyDesktop();
    } else {
      try {
        await navigator.clipboard.writeText(body);
      } catch {
        /* ignore */
      }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div
      className={[
        "group flex w-full gap-2 px-1 sm:gap-3",
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
          "relative max-w-[min(100%,28rem)] rounded-2xl border px-3.5 py-2.5 shadow-sm sm:max-w-xl",
          isUser
            ? "border-blue-400/20 bg-blue-600/20 text-slate-50"
            : message.error
              ? "border-rose-400/25 bg-rose-500/10 text-rose-50"
              : "border-white/10 bg-slate-900/90 text-slate-100",
        ].join(" ")}
      >
        {/* Desktop copy */}
        {body && !streaming ? (
          <button
            type="button"
            onClick={() => void handleCopy()}
            className={[
              "absolute -right-1 -top-1 hidden h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-slate-900/90 text-slate-400 shadow transition",
              "hover:text-slate-100 sm:group-hover:flex",
              copied ? "flex text-emerald-400" : "",
            ].join(" ")}
            title={copied ? "Copied" : "Copy"}
            aria-label={copied ? "Copied" : "Copy message"}
          >
            {copied ? (
              <Check className="h-3.5 w-3.5" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        ) : null}

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
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {body}
            {streaming ? (
              <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
            ) : null}
          </p>
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
// MessageList
// ---------------------------------------------------------------------------

export default function MessageList({
  messages,
  isLoading = false,
  onCopy,
  onRetry,
  onCite,
  onCitationClick,
  emptyTitle = "Start a conversation",
  emptyDescription = "Ask a question grounded in your indexed documents. On mobile, swipe a message left for Copy, Retry, or Sources.",
  className = "",
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [activeSwipeId, setActiveSwipeId] = useState<string | null>(null);

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

  const copyMessage = useCallback(
    async (m: ChatMessage) => {
      if (onCopy) {
        onCopy(m);
        return;
      }
      const text = m.error || m.content || "";
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        /* ignore */
      }
    },
    [onCopy]
  );

  return (
    <div
      ref={listRef}
      className={[
        "min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-3 sm:px-4",
        className,
      ].join(" ")}
      role="log"
      aria-live="polite"
      aria-relevant="additions"
    >
      {messages.length === 0 ? (
        <div className="flex h-full min-h-[12rem] flex-col items-center justify-center px-4 text-center">
          <p className="text-sm font-medium text-slate-300">{emptyTitle}</p>
          <p className="mt-1 max-w-sm text-xs text-slate-500">
            {emptyDescription}
          </p>
        </div>
      ) : (
        <ul className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          {messages.map((m) => (
            <li key={m.id}>
              <SwipeableRow
                message={m}
                isActive={activeSwipeId === m.id}
                onActivate={() => setActiveSwipeId(m.id)}
                onCopy={copyMessage}
                onRetry={
                  m.role === "assistant" && m.error && onRetry
                    ? onRetry
                    : undefined
                }
                onCite={
                  m.citations?.length && onCite ? onCite : undefined
                }
              >
                <MessageBubble
                  message={m}
                  onCitationClick={(c) => onCitationClick?.(c, m)}
                  onCopyDesktop={() => void copyMessage(m)}
                />
              </SwipeableRow>
            </li>
          ))}
        </ul>
      )}
      <div ref={bottomRef} />
    </div>
  );
}