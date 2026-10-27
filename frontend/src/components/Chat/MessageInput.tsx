/**
 * MessageInput — chat composer with voice dictation + copy draft.
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Send,
  Square,
  Loader2,
  Paperclip,
  X,
  Mic,
  MicOff,
  Copy,
  Check,
} from "lucide-react";

export interface MessageInputProps {
  onSend: (text: string) => void;
  onStop?: () => void;
  disabled?: boolean;
  isLoading?: boolean;
  placeholder?: string;
  maxLength?: number;
  value?: string;
  onChangeText?: (text: string) => void;
  autoFocus?: boolean;
  alwaysShowCount?: boolean;
  leading?: ReactNode;
  onAttach?: (files: FileList) => void;
  accept?: string;
  enableVoice?: boolean;
  voiceLang?: string;
  enableCopy?: boolean;
  className?: string;
}

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
};

function getSpeechRecognition():
  | (new () => SpeechRecognitionLike)
  | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const MessageInput = ({
  onSend,
  onStop,
  disabled = false,
  isLoading = false,
  placeholder = "Ask about your documents…",
  maxLength = 4000,
  value: controlledValue,
  onChangeText,
  autoFocus = false,
  alwaysShowCount = false,
  leading,
  onAttach,
  accept,
  enableVoice = true,
  voiceLang = typeof navigator !== "undefined" ? navigator.language : "en-US",
  enableCopy = true,
  className = "",
}: MessageInputProps) => {
  const [internal, setInternal] = useState("");
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : internal;

  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const baseTextRef = useRef("");
  const copiedTimerRef = useRef<number | null>(null);

  const hintId = useId();
  const inputId = useId();

  const SpeechRecognitionCtor = getSpeechRecognition();
  const voiceSupported = Boolean(enableVoice && SpeechRecognitionCtor);

  const setValue = useCallback(
    (next: string) => {
      const clipped = next.slice(0, maxLength);
      if (!isControlled) setInternal(clipped);
      onChangeText?.(clipped);
    },
    [isControlled, maxLength, onChangeText]
  );

  const canSend = value.trim().length > 0 && !disabled && !isLoading;
  const canCopy = enableCopy && value.trim().length > 0 && !disabled;
  const nearLimit = value.length >= maxLength * 0.9;
  const atLimit = value.length >= maxLength;

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.abort();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
      if (copiedTimerRef.current != null) {
        window.clearTimeout(copiedTimerRef.current);
      }
    };
  }, []);

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
    setListening(false);
  }, []);

  const startListening = useCallback(() => {
    if (!SpeechRecognitionCtor || disabled || isLoading) return;

    setVoiceError(null);
    try {
      recognitionRef.current?.abort();
    } catch {
      /* ignore */
    }

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = voiceLang;
    recognition.continuous = true;
    recognition.interimResults = true;
    baseTextRef.current = value.trim() ? `${value.trim()} ` : "";

    recognition.onresult = (event) => {
      let finalChunk = "";
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const piece = event.results[i][0]?.transcript ?? "";
        if (event.results[i].isFinal) finalChunk += piece;
        else interim += piece;
      }
      if (finalChunk) {
        baseTextRef.current = `${baseTextRef.current}${finalChunk}`.slice(
          0,
          maxLength
        );
      }
      setValue(`${baseTextRef.current}${interim}`.slice(0, maxLength));
    };

    recognition.onerror = (event) => {
      const err = event.error;
      if (err === "not-allowed" || err === "service-not-allowed") {
        setVoiceError("Microphone permission denied");
      } else if (err === "no-speech") {
        setVoiceError("No speech detected");
      } else if (err !== "aborted") {
        setVoiceError("Voice input failed");
      }
      setListening(false);
    };

    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;

    try {
      recognition.start();
      setListening(true);
    } catch {
      setVoiceError("Could not start microphone");
      setListening(false);
    }
  }, [
    SpeechRecognitionCtor,
    disabled,
    isLoading,
    voiceLang,
    value,
    maxLength,
    setValue,
  ]);

  const toggleVoice = () => {
    if (listening) stopListening();
    else startListening();
  };

  const handleCopy = async () => {
    const text = value.trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (copiedTimerRef.current != null) {
        window.clearTimeout(copiedTimerRef.current);
      }
      copiedTimerRef.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      try {
        const el = textareaRef.current;
        if (el) {
          el.focus();
          el.select();
          document.execCommand("copy");
          setCopied(true);
          copiedTimerRef.current = window.setTimeout(
            () => setCopied(false),
            1500
          );
        }
      } catch {
        /* ignore */
      }
    }
  };

  const handleSubmit = useCallback(() => {
    const text = value.trim();
    if (!text || disabled || isLoading) return;
    if (listening) stopListening();
    onSend(text);
    setValue("");
    setCopied(false);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.style.height = "auto";
        el.focus();
      }
    });
  }, [value, disabled, isLoading, onSend, setValue, listening, stopListening]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const clear = () => {
    if (listening) stopListening();
    setValue("");
    setCopied(false);
    textareaRef.current?.focus();
  };

  return (
    <div
      className={[
        "shrink-0 border-t border-white/10 bg-slate-950/90 backdrop-blur-md",
        "px-3 py-3 sm:px-4",
        className,
      ].join(" ")}
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        <div
          className={[
            "flex items-end gap-2 rounded-2xl border bg-white/[0.03] p-2 shadow-inner transition",
            listening
              ? "border-rose-400/40 ring-2 ring-rose-500/20"
              : "border-white/10 focus-within:border-blue-400/40 focus-within:ring-2 focus-within:ring-blue-500/15",
            disabled ? "opacity-60" : "",
          ].join(" ")}
        >
          <div className="flex shrink-0 items-center gap-1 pb-0.5">
            {leading}

            {onAttach ? (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  accept={accept}
                  multiple
                  onChange={(e) => {
                    if (e.target.files?.length) onAttach(e.target.files);
                    e.target.value = "";
                  }}
                />
                <button
                  type="button"
                  disabled={disabled || isLoading}
                  onClick={() => fileRef.current?.click()}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 transition hover:bg-white/5 hover:text-slate-200 disabled:opacity-40"
                  title="Attach"
                  aria-label="Attach files"
                >
                  <Paperclip className="h-4 w-4" />
                </button>
              </>
            ) : null}

            {/* 1. Voice dictation */}
            {enableVoice ? (
              <button
                type="button"
                disabled={disabled || isLoading || !voiceSupported}
                onClick={toggleVoice}
                className={[
                  "inline-flex h-9 w-9 items-center justify-center rounded-xl transition",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40",
                  "disabled:opacity-40",
                  listening
                    ? "bg-rose-500/20 text-rose-300 hover:bg-rose-500/30"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
                ].join(" ")}
                title={
                  !voiceSupported
                    ? "Voice input not supported in this browser"
                    : listening
                      ? "Stop listening"
                      : "Start voice input"
                }
                aria-label={
                  listening ? "Stop voice input" : "Start voice input"
                }
                aria-pressed={listening}
              >
                {listening ? (
                  <MicOff className="h-4 w-4 animate-pulse" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </button>
            ) : null}
          </div>

          <label htmlFor={inputId} className="sr-only">
            Message
          </label>
          <textarea
            id={inputId}
            ref={textareaRef}
            rows={1}
            value={value}
            maxLength={maxLength}
            disabled={disabled}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={listening ? "Listening… speak now" : placeholder}
            aria-describedby={hintId}
            className={[
              "max-h-40 min-h-[40px] flex-1 resize-none bg-transparent",
              "px-1 py-2 text-sm leading-relaxed text-slate-100",
              "placeholder:text-slate-500 focus:outline-none disabled:cursor-not-allowed",
            ].join(" ")}
          />

          <div className="flex shrink-0 items-center gap-1.5 pb-0.5">
            {/* 2. Copy to clipboard */}
            {enableCopy ? (
              <button
                type="button"
                onClick={() => void handleCopy()}
                disabled={!canCopy}
                className={[
                  "inline-flex h-9 w-9 items-center justify-center rounded-xl transition",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/40",
                  "disabled:opacity-30",
                  copied
                    ? "text-emerald-400"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
                ].join(" ")}
                title={copied ? "Copied" : "Copy message"}
                aria-label={copied ? "Copied" : "Copy message to clipboard"}
              >
                {copied ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </button>
            ) : null}

            {value.length > 0 && !isLoading ? (
              <button
                type="button"
                onClick={clear}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-500 transition hover:bg-white/5 hover:text-slate-300 sm:hidden"
                title="Clear"
                aria-label="Clear message"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}

            {isLoading && onStop ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl border border-rose-400/30 bg-rose-500/15 px-3 text-rose-200 transition hover:bg-rose-500/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
                title="Stop generation"
                aria-label="Stop generation"
              >
                <Square size={14} className="fill-current" aria-hidden="true" />
                <span className="text-xs font-medium">Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSend}
                className={[
                  "inline-flex h-10 w-10 items-center justify-center rounded-xl text-white transition",
                  "bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-900/25",
                  "hover:from-blue-500 hover:to-indigo-500",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/50",
                  "disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
                ].join(" ")}
                title="Send message"
                aria-label="Send message"
              >
                {isLoading ? (
                  <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                ) : (
                  <Send size={18} aria-hidden="true" />
                )}
              </button>
            )}
          </div>
        </div>

        <div
          id={hintId}
          className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-0.5 text-[11px] text-slate-500"
        >
          <p>
            {listening ? (
              <span className="font-medium text-rose-300/90">
                Listening — tap the mic to stop
              </span>
            ) : voiceError ? (
              <span className="text-amber-400/90">{voiceError}</span>
            ) : copied ? (
              <span className="font-medium text-emerald-400/90">
                Copied to clipboard
              </span>
            ) : (
              <>
                <span className="hidden sm:inline">
                  Enter to send · Shift+Enter for new line
                  {voiceSupported ? " · Mic to dictate" : ""}
                </span>
                <span className="sm:hidden">
                  Tap send
                  {voiceSupported ? " · Mic to dictate" : ""}
                </span>
              </>
            )}
            {isLoading ? (
              <span className="ml-2 inline-flex items-center gap-1 text-blue-300/90">
                <Loader2 size={10} className="animate-spin" />
                Generating…
              </span>
            ) : null}
          </p>

          {(alwaysShowCount || nearLimit) && (
            <span
              className={[
                "tabular-nums",
                atLimit
                  ? "font-medium text-rose-400"
                  : nearLimit
                    ? "text-amber-400/90"
                    : "text-slate-500",
              ].join(" ")}
            >
              {value.length}/{maxLength}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default MessageInput;