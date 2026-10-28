import React, { useEffect, useMemo, useRef, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
};

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let alive = true;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE_URL}/chat/history`, {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
        });

        if (!res.ok) throw new Error(`Chat history failed (${res.status})`);

        const data = (await res.json()) as { messages?: ChatMessage[]; data?: ChatMessage[] };
        if (!alive) return;
        setMessages(data.messages ?? data.data ?? []);
      } catch (e: any) {
        if (!alive) return;
        setError(e?.message ?? "Failed to load chat history.");
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    }

    load();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const canSend = useMemo(() => draft.trim().length > 0 && !sending, [draft, sending]);

  async function sendMessage() {
    const text = draft.trim();
    if (!text) return;

    setSending(true);
    setError(null);

    // optimistic UI
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setDraft("");

    try {
      const res = await fetch(`${API_BASE_URL}/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ message: text }),
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `Send failed (${res.status})`);
      }

      const data = (await res.json()) as { message?: ChatMessage; messages?: ChatMessage[]; reply?: string };
      const assistantMsg: ChatMessage =
        data.message ??
        (data.messages && data.messages.length
          ? data.messages[data.messages.length - 1]
          : {
              id: crypto.randomUUID(),
              role: "assistant",
              content: data.reply ?? "",
              createdAt: new Date().toISOString(),
            });

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      setError(e?.message ?? "Failed to send message.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="p-4 md:p-6 flex flex-col h-[calc(100vh-2rem)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Chat</h1>
          <p className="text-slate-600 mt-1">Ask questions and review responses.</p>
        </div>
      </div>

      <section className="mt-6 flex-1 flex flex-col overflow-hidden rounded-lg border border-slate-200">
        <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
          <div className="text-sm font-semibold text-slate-800">Conversation</div>
        </div>

        {loading ? (
          <div className="p-6 text-slate-600">Loading chat…</div>
        ) : (
          <div className="flex-1 overflow-auto p-4 space-y-3">
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-800 text-sm">
                {error}
              </div>
            )}

            {messages.length === 0 ? (
              <div className="text-center text-slate-600 mt-10">
                No messages yet. Send a message to start.
              </div>
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-xl px-4 py-3 whitespace-pre-wrap text-sm leading-relaxed border ${
                      m.role === "user"
                        ? "bg-slate-900 text-white border-slate-900"
                        : m.role === "assistant"
                        ? "bg-white text-slate-900 border-slate-200"
                        : "bg-slate-50 text-slate-700 border-slate-200"
                    }`}
                  >
                    <div className="font-medium mb-1 opacity-90">
                      {m.role === "user" ? "You" : m.role === "assistant" ? "Assistant" : "System"}
                    </div>
                    <div>{m.content}</div>
                    <div className="mt-2 text-xs opacity-70">{new Date(m.createdAt).toLocaleString()}</div>
                  </div>
                </div>
              ))
            )}

            <div ref={endRef} />
          </div>
        )}

        <div className="border-t border-slate-200 p-3 bg-white">
          <label className="sr-only" htmlFor="chat-input">
            Message
          </label>
          <div className="flex gap-2">
            <input
              id="chat-input"
              className="flex-1 rounded-md border border-slate-200 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-300"
              placeholder="Type your message…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendMessage();
              }}
              disabled={sending || loading}
            />
            <button
              className="rounded-md bg-slate-900 text-white px-4 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-60"
              onClick={sendMessage}
              disabled={!canSend}
              aria-disabled={!canSend}
              title="Ctrl/⌘ + Enter to send"
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
          <div className="mt-2 text-xs text-slate-500">
            Press <span className="font-medium">Ctrl/⌘ + Enter</span> to send.
          </div>
        </div>
      </section>
    </main>
  );
}