import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Send,
  Bot,
  User,
  FileText,
  Loader2,
  Sparkles,
  AlertCircle,
  Trash2,
  StopCircle,
  MessageSquare,
} from 'lucide-react';
import { apiClient, type ApiErrorDetails } from '../../lib/apiClient';

type Source = {
  id?: string;
  title?: string;
  file_name?: string;
  source_file?: string;
  page?: number;
  similarity?: number;
  score?: number;
  text?: string;
  [key: string]: unknown;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  confidence?: number;
  latencyMs?: number;
  isError?: boolean;
};

const SUGGESTIONS = [
  'How long are customer account records retained?',
  'What is the critical threat escalation policy?',
  'Summarize quarantine handling for flagged documents.',
];

function newId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
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
  };

  if (e?.code === 'ECONNABORTED') {
    return 'The query timed out. Try a shorter question or lower Top-K.';
  }
  if (e?.code === 'CIRCUIT_OPEN') {
    return 'API circuit breaker is open. Wait a moment and retry.';
  }
  if (
    e?.name === 'AbortError' ||
    e?.name === 'CanceledError' ||
    e?.code === 'ERR_CANCELED'
  ) {
    return 'Request cancelled.';
  }

  const detail =
    e?.response?.data?.detail ||
    e?.response?.data?.error ||
    e?.response?.data?.message ||
    (typeof e?.message === 'string'
      ? e.message
      : e?.message && typeof e.message === 'object'
        ? (e.message as { detail?: string }).detail
        : undefined);

  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail) return JSON.stringify(detail);
  if (e?.status === 404) {
    return 'RAG endpoint not found (404). Deploy /api/v1/rag/query on the backend.';
  }
  return 'Could not reach the RAG backend. Check VITE_API_URL and CORS_ORIGINS.';
}

function normalizeSources(raw: unknown): Source[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((s, i) => {
    if (!s || typeof s !== 'object') {
      return { id: `src-${i}`, title: String(s) };
    }
    const o = s as Record<string, unknown>;
    const payload =
      o.payload && typeof o.payload === 'object'
        ? (o.payload as Record<string, unknown>)
        : {};
    return {
      id: String(o.id ?? payload.chunk_id ?? i),
      title: String(
        o.title ??
          o.file_name ??
          o.source_file ??
          payload.source_file ??
          payload.doc_id ??
          `Document ${i + 1}`
      ),
      file_name: (o.file_name ?? payload.source_file) as string | undefined,
      source_file: (o.source_file ?? payload.source_file) as string | undefined,
      page: typeof o.page === 'number' ? o.page : undefined,
      similarity:
        typeof o.similarity === 'number'
          ? o.similarity
          : typeof o.score === 'number'
            ? o.score
            : undefined,
      text: String(o.text ?? payload.text ?? ''),
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
  confidence_score?: number;
  processing_time_ms?: number;
}> {
  if (typeof apiClient.queryRag === 'function') {
    return apiClient.queryRag({ query, top_k: topK }, signal);
  }
  return apiClient.post(
    '/api/v1/rag/query',
    { query, top_k: topK },
    { signal, timeout: 90_000 }
  ) as Promise<{
    answer?: string;
    result?: string;
    sources?: unknown;
    confidence_score?: number;
    processing_time_ms?: number;
  }>;
}

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    'Hello! I am ready to answer questions about your ingested documents. Ask me anything — answers include citations when the vector store has matching chunks.',
  sources: [],
};

export default function RAGChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([{ ...WELCOME }]);
  const [input, setInput] = useState('');
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const onlyWelcome = messages.length === 1 && messages[0]?.id === 'welcome';

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
  };

  const clearChat = () => {
    stop();
    setMessages([{ ...WELCOME, id: newId() }]);
    setInput('');
    inputRef.current?.focus();
  };

  const runQuery = async (userMessage: string) => {
    if (!userMessage || loading) return;

    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', content: userMessage },
    ]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = performance.now();

    try {
      const data = await callRag(userMessage, topK, controller.signal);

      const answer =
        data.answer ||
        data.result ||
        'No response generated from the documents.';
      const sources = normalizeSources(data.sources);
      const latencyMs =
        typeof data.processing_time_ms === 'number'
          ? data.processing_time_ms
          : Math.round(performance.now() - t0);

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          content: answer,
          sources,
          confidence: data.confidence_score,
          latencyMs,
        },
      ]);
    } catch (err) {
      const name = (err as { name?: string })?.name;
      const code = (err as { code?: string })?.code;
      const cancelled =
        name === 'AbortError' ||
        name === 'CanceledError' ||
        code === 'ERR_CANCELED';

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          content: cancelled ? 'Request cancelled.' : errorMessage(err),
          sources: [],
          isError: true,
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
    setInput('');
    await runQuery(userMessage);
  };

  const onSuggestion = (text: string) => {
    if (loading) return;
    setInput('');
    void runQuery(text);
  };

  return (
    <div className="w-full max-w-3xl mx-auto flex flex-col min-h-[560px] h-[min(640px,70vh)] bg-white rounded-xl shadow-md border border-gray-100 overflow-hidden">
      <div className="px-6 py-4 bg-gray-50 border-b border-gray-100 flex items-center justify-between gap-3 flex-wrap shrink-0">
        <div className="flex items-center space-x-2">
          <Sparkles className="w-5 h-5 text-blue-600" />
          <h2 className="font-semibold text-gray-800">Document Intelligence Assistant</h2>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 flex items-center gap-1.5">
            Top-K
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) =>
                setTopK(Math.min(20, Math.max(1, Number(e.target.value) || 5)))
              }
              className="w-14 px-1.5 py-1 border border-gray-200 rounded-md text-xs bg-white"
              disabled={loading}
            />
          </label>
          <button
            type="button"
            onClick={clearChat}
            className="text-xs text-gray-500 hover:text-gray-800 inline-flex items-center gap-1 px-2 py-1 rounded-md hover:bg-gray-100"
            title="Clear chat"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear
          </button>
          <span className="text-xs bg-blue-100 text-blue-700 px-2.5 py-1 rounded-full font-medium">
            RAG Active
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-slate-50/80 min-h-[320px]">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex items-start space-x-3 ${
              msg.role === 'user' ? 'flex-row-reverse space-x-reverse' : ''
            }`}
          >
            <div
              className={`w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : msg.isError
                    ? 'bg-red-50 border border-red-200 text-red-600'
                    : 'bg-white border border-gray-200 text-blue-600 shadow-sm'
              }`}
            >
              {msg.role === 'user' ? (
                <User className="w-5 h-5" />
              ) : msg.isError ? (
                <AlertCircle className="w-5 h-5" />
              ) : (
                <Bot className="w-5 h-5" />
              )}
            </div>

            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 shadow-sm text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-tr-none'
                  : msg.isError
                    ? 'bg-red-50 border border-red-100 text-red-800 rounded-tl-none'
                    : 'bg-white border border-gray-100 text-gray-800 rounded-tl-none'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>

              {(msg.confidence != null || msg.latencyMs != null) && !msg.isError && (
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-gray-400">
                  {msg.confidence != null && (
                    <span>Confidence {(msg.confidence * 100).toFixed(0)}%</span>
                  )}
                  {msg.latencyMs != null && <span>{msg.latencyMs} ms</span>}
                </div>
              )}

              {msg.sources && msg.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wider">
                    Sources &amp; citations
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {msg.sources.map((source, sIdx) => (
                      <div
                        key={source.id || sIdx}
                        className="text-xs bg-gray-50 text-gray-700 px-2.5 py-1.5 rounded-md border border-gray-200/60"
                      >
                        <div className="inline-flex items-center gap-1.5 font-medium flex-wrap">
                          <FileText className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
                          <span className="truncate max-w-[220px]">
                            {source.title ||
                              source.file_name ||
                              source.source_file ||
                              source.id ||
                              `Document ${sIdx + 1}`}
                          </span>
                          {source.page != null && (
                            <span className="text-gray-400 font-normal">
                              (p. {source.page})
                            </span>
                          )}
                          {source.similarity != null && (
                            <span className="text-gray-400 font-normal">
                              · {(Number(source.similarity) * 100).toFixed(0)}%
                            </span>
                          )}
                        </div>
                        {source.text ? (
                          <p className="mt-1 text-gray-500 line-clamp-2 pl-5">
                            {String(source.text)}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {onlyWelcome && !loading && (
          <div className="pl-12 space-y-2">
            <p className="text-xs text-gray-400 flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5" />
              Try a sample question
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onSuggestion(s)}
                  className="text-left text-xs px-3 py-2 rounded-xl border border-blue-100 bg-white text-blue-700 hover:bg-blue-50 hover:border-blue-200 transition-colors max-w-full"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {loading && (
          <div className="flex items-start space-x-3">
            <div className="w-9 h-9 rounded-full bg-white border border-gray-200 text-blue-600 shadow-sm flex items-center justify-center">
              <Bot className="w-5 h-5" />
            </div>
            <div className="bg-white border border-gray-100 text-gray-500 rounded-2xl rounded-tl-none px-4 py-3 shadow-sm text-sm flex items-center space-x-2 flex-wrap">
              <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
              <span>Searching vectors &amp; synthesizing answer…</span>
              <button
                type="button"
                onClick={stop}
                className="ml-2 text-xs text-gray-400 hover:text-red-600 inline-flex items-center gap-1"
              >
                <StopCircle className="w-3.5 h-3.5" />
                Stop
              </button>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form
        onSubmit={(e) => void handleSend(e)}
        className="p-4 bg-white border-t border-gray-100 flex items-center space-x-3 shrink-0"
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about your uploaded documents…"
          className="flex-1 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:border-blue-500 focus:bg-white text-sm transition-all"
          disabled={loading}
          maxLength={4000}
          autoComplete="off"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium transition-colors flex items-center space-x-2 disabled:opacity-50 shadow-sm"
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <span>Send</span>
              <Send className="w-4 h-4" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}