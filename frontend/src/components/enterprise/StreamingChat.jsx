import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Sparkles, Trash2, ShieldAlert, FileText, ArrowDown } from 'lucide-react';

export default function StreamingChat() {
  const INITIAL_MESSAGE = {
    role: 'assistant',
    content: 'Enterprise Document Intelligence online. Ask me anything about your ingested vector documents, security policies, or threat telemetry.',
    sources: []
  };

  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleClearChat = () => {
    setMessages([INITIAL_MESSAGE]);
  };

  const handleQuickPrompt = (promptText) => {
    setInput(promptText);
  };

  const handleSend = async (e) => {
    e?.preventDefault();
    if (!input.trim() || loading) return;

    const userQuery = input.trim();
    setInput('');
    
    // Append user message & placeholder assistant response
    setMessages(prev => [
      ...prev,
      { role: 'user', content: userQuery, sources: [] },
      { role: 'assistant', content: '', sources: [] }
    ]);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/intelligence/query/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('doc_intelligence_token') || ''}`
        },
        body: JSON.stringify({ query: userQuery })
      });

      if (!response.ok) {
        throw new Error(`Streaming request failed: ${response.status} ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';
      let extractedSources = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith('data:')) {
            const dataContent = trimmed.replace('data:', '').trim();

            if (dataContent === '[DONE]') break;

            // Handle optional JSON objects in SSE stream (e.g., metadata/sources)
            if (dataContent.startsWith('{') && dataContent.endsWith('}')) {
              try {
                const parsed = JSON.parse(dataContent);
                if (parsed.sources) extractedSources = parsed.sources;
                if (parsed.text) assistantResponse += parsed.text;
              } catch {
                assistantResponse += dataContent;
              }
            } else {
              assistantResponse += dataContent;
            }

            setMessages(prev => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: 'assistant',
                content: assistantResponse,
                sources: extractedSources
              };
              return updated;
            });
          } else if (!trimmed.startsWith(':')) {
            // Raw string chunk fallback
            assistantResponse += trimmed;
            setMessages(prev => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: 'assistant',
                content: assistantResponse,
                sources: extractedSources
              };
              return updated;
            });
          }
        }
      }
    } catch (err) {
      console.error("Streaming error:", err);
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `[System Error: Unable to stream response from backend. ${err.message}]`,
          sources: []
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[600px] shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="p-4 bg-slate-900/80 backdrop-blur-md border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 bg-blue-600/10 border border-blue-500/20 rounded-lg text-blue-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100 flex items-center space-x-2">
              <span>RAG Intelligence Copilot</span>
            </h3>
            <p className="text-[11px] text-slate-400">Real-time SSE vector streaming active</p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <span className="inline-flex items-center space-x-1.5 text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2.5 py-1 rounded-full font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>SSE Connected</span>
          </span>

          <button
            onClick={handleClearChat}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition"
            title="Clear Chat"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Chat Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-950/40">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex items-start space-x-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="p-2 bg-blue-600/10 border border-blue-500/20 rounded-lg text-blue-400 flex-shrink-0 mt-0.5">
                <Bot className="w-4 h-4" />
              </div>
            )}

            <div className={`max-w-[85%] space-y-2`}>
              <div
                className={`p-3.5 rounded-xl text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-br-none shadow-md shadow-blue-600/10'
                    : 'bg-slate-900/90 text-slate-200 rounded-bl-none border border-slate-800 shadow-md'
                }`}
              >
                {msg.content || (
                  <span className="inline-flex items-center space-x-2 text-slate-400">
                    <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping"></span>
                    <span>Querying vector store & generating stream...</span>
                  </span>
                )}
              </div>

              {/* Source citations badge row */}
              {msg.sources && msg.sources.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {msg.sources.map((src, sIdx) => (
                    <span
                      key={sIdx}
                      className="inline-flex items-center space-x-1 text-[10px] bg-slate-800/80 text-slate-400 border border-slate-700/60 px-2 py-0.5 rounded-md"
                    >
                      <FileText className="w-3 h-3 text-blue-400" />
                      <span>{src.title || src.filename || `Doc #${sIdx + 1}`}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {msg.role === 'user' && (
              <div className="p-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-300 flex-shrink-0 mt-0.5">
                <User className="w-4 h-4" />
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompts Bar for Demos */}
      {messages.length <= 2 && (
        <div className="px-4 py-2 bg-slate-900/60 border-t border-slate-800/60 flex items-center space-x-2 overflow-x-auto text-xs text-slate-400">
          <span className="font-medium text-slate-500 whitespace-nowrap">Try Demo Prompts:</span>
          <button
            onClick={() => handleQuickPrompt("Summarize all ingested security policy documents.")}
            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-md transition whitespace-nowrap"
          >
            "Summarize security policies"
          </button>
          <button
            onClick={() => handleQuickPrompt("Are there any phishing risk factors mentioned in the vectors?")}
            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-md transition whitespace-nowrap"
          >
            "Analyze phishing risks"
          </button>
        </div>
      )}

      {/* Input Bar */}
      <form onSubmit={handleSend} className="p-3 bg-slate-900 border-t border-slate-800 flex items-center space-x-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about your vector database..."
          className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="p-2.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}