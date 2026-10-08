"use client";

import React, { useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Search,
  Terminal,
  AlertCircle,
  FileText,
  Sparkles,
  Loader2,
  Copy,
  Check,
  Zap,
  ChevronRight,
  X,
  Database,
} from "lucide-react";

// --- Types & Interfaces ---

interface Source {
  index: number;
  document_id: string;
  file_name: string;
  score: number;
  content?: string;
}

interface PerformanceMetrics {
  ttftMs: number | null;
  totalTimeMs: number | null;
  tokenCount: number;
}

export default function ThreatRetrievalDashboard() {
  const [query, setQuery] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [answer, setAnswer] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  
  // Drawer / Inspection state
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);

  // Performance metrics tracking
  const [metrics, setMetrics] = useState<PerformanceMetrics>({
    ttftMs: null,
    totalTimeMs: null,
    tokenCount: 0,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  const handleStreamSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isLoading) return;

    // Reset state
    setAnswer("");
    setSources([]);
    setError(null);
    setIsLoading(true);
    setSelectedSource(null);
    setMetrics({ ttftMs: null, totalTimeMs: null, tokenCount: 0 });

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const startTime = performance.now();
    let ttftRecorded = false;
    let localTokenCount = 0;

    try {
      const response = await fetch("http://localhost:8000/retrieval/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          query: query,
          top_k: 5,
          score_threshold: 0.2,
          hybrid: true,
          model: "gpt-4o-mini",
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP Error [${response.status}]: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("ReadableStream not supported in this browser.");

      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;

          const jsonString = trimmed.replace(/^data:\s*/, "");
          if (!jsonString) continue;

          try {
            const event = JSON.parse(jsonString);

            if (event.type === "sources") {
              setSources(event.sources || []);
            } else if (event.type === "token") {
              if (!ttftRecorded) {
                const ttft = performance.now() - startTime;
                setMetrics((prev) => ({ ...prev, ttftMs: Math.round(ttft) }));
                ttftRecorded = true;
              }
              localTokenCount += 1;
              setAnswer((prev) => prev + event.content);
              setMetrics((prev) => ({ ...prev, tokenCount: localTokenCount }));
            } else if (event.type === "error") {
              setError(event.message || "An unexpected streaming error occurred.");
            } else if (event.type === "done") {
              const totalElapsed = performance.now() - startTime;
              setMetrics((prev) => ({ ...prev, totalTimeMs: Math.round(totalElapsed) }));
              setIsLoading(false);
            }
          } catch (err) {
            console.error("Failed to parse event chunk:", err);
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setError(err.message || "Failed to establish stream connection with server.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = () => {
    if (!answer) return;
    navigator.clipboard.writeText(answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative w-full max-w-5xl mx-auto p-6 space-y-6 text-slate-100 bg-slate-950 border border-slate-800 rounded-xl shadow-2xl font-sans">
      
      {/* 1. Dashboard Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
            <Terminal className="w-6 h-6 text-emerald-400"/>
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-wide text-white">
              Phishing & Threat Intelligence Stream
            </h1>
            <p className="text-xs text-slate-400">
              Qdrant Hybrid Vector Search & Real-time LLM Synthesis Engine
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-mono text-emerald-400 uppercase tracking-wider">
            System Ready
          </span>
        </div>
      </div>

      {/* 2. Query Input & Actions */}
      <form onSubmit={handleStreamSubmit} className="space-y-3">
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a threat query (e.g., 'How do detectors handle spoofed headers?')..."
            className="w-full py-3.5 pl-4 pr-32 bg-slate-900/90 border border-slate-800 rounded-lg text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 transition-all shadow-inner"
          />
          <div className="absolute right-2 top-2 bottom-2 flex space-x-2">
            {isLoading && (
              <button
                type="button"
                onClick={() => abortControllerRef.current?.abort()}
                className="px-3 bg-red-950/80 hover:bg-red-900 border border-red-800 text-red-200 font-medium text-xs rounded-md transition-all flex items-center space-x-1"
              >
                <X className="w-3.5 h-3.5"/>
                <span>Stop</span>
              </button>
            )}
            <button
              type="submit"
              disabled={isLoading || !query.trim()}
              className="px-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-medium text-xs rounded-md transition-all flex items-center space-x-2 shadow-lg"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-emerald-300"/>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5"/>
                  <span>Execute</span>
                </>
              )}
            </button>
          </div>
        </div>
      </form>

      {/* 3. Error Alert Banner */}
      {error && (
        <div className="p-4 bg-red-950/40 border border-red-800/60 rounded-lg flex items-center justify-between text-red-300 text-sm animate-in fade-in">
          <div className="flex items-center space-x-3">
            <AlertCircle className="w-5 h-5 flex-shrink-0 text-red-400"/>
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-xs text-red-400 hover:text-red-200 underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 4. Retrieved Vector Sources Cards */}
      {sources.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs uppercase font-semibold text-slate-400 tracking-wider flex items-center space-x-2">
              <Database className="w-3.5 h-3.5 text-sky-400"/>
              <span>Retrieved Threat Documents ({sources.length})</span>
            </h2>
            <span className="text-[10px] text-slate-500 font-mono">
              Hybrid Dense + Sparse Match
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
            {sources.map((src) => (
              <div
                key={src.index}
                onClick={() => setSelectedSource(src)}
                className="p-3 bg-slate-900/80 hover:bg-slate-850 border border-slate-800 hover:border-slate-700 rounded-lg cursor-pointer transition-all group space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-300 group-hover:text-emerald-400 transition-colors truncate max-w-[180px]">
                    [{src.index}] {src.file_name}
                  </span>
                  <ChevronRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-300 transition-colors"/>
                </div>
                <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono">
                  <span>ID: {src.document_id.slice(0, 8)}...</span>
                  <span className="text-emerald-400 bg-emerald-950/60 border border-emerald-800/50 px-1.5 py-0.5 rounded">
                    Score: {(src.score * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Live Synthesis Output Panel */}
      {(answer || isLoading) && (
        <div className="p-5 bg-slate-900/50 border border-slate-800 rounded-lg space-y-4 shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-emerald-400"/>
              <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">
                Synthesized Threat Analysis
              </span>
            </div>

            <div className="flex items-center space-x-3">
              {/* Telemetry stats */}
              {metrics.ttftMs && (
                <span className="text-[10px] font-mono text-slate-400 flex items-center space-x-1">
                  <Zap className="w-3 h-3 text-amber-400"/>
                  <span>TTFT: {metrics.ttftMs}ms</span>
                </span>
              )}
              {metrics.tokenCount > 0 && (
                <span className="text-[10px] font-mono text-slate-400">
                  Tokens: {metrics.tokenCount}
                </span>
              )}

              {/* Copy button */}
              {answer && (
                <button
                  onClick={handleCopy}
                  className="p-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded text-xs transition-all flex items-center space-x-1"
                  title="Copy to clipboard"
                >
                  {copied ? (
                    <Check className="w-3.5 h-3.5 text-emerald-400"/>
                  ) : (
                    <Copy className="w-3.5 h-3.5"/>
                  )}
                </button>
              )}
            </div>
          </div>

          {/* Rendered Markdown Body */}
          <div className="prose prose-invert prose-slate max-w-none text-sm text-slate-200 leading-relaxed font-sans">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
            {isLoading && (
              <span className="inline-block w-2 h-4 ml-1 bg-emerald-400 animate-pulse align-middle" />
            )}
          </div>
        </div>
      )}

      {/* 6. Document Inspection Side Drawer */}
      {selectedSource && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex justify-end animate-in fade-in">
          <div className="w-full max-w-md bg-slate-900 border-l border-slate-800 h-full p-6 space-y-4 flex flex-col justify-between shadow-2xl">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center space-x-2">
                  <FileText className="w-4 h-4 text-sky-400"/>
                  <h3 className="text-sm font-bold text-white truncate max-w-[280px]">
                    {selectedSource.file_name}
                  </h3>
                </div>
                <button
                  onClick={() => setSelectedSource(null)}
                  className="p-1 text-slate-400 hover:text-white rounded"
                >
                  <X className="w-5 h-5"/>
                </button>
              </div>

              <div className="space-y-2 text-xs font-mono">
                <div className="flex justify-between py-1 border-b border-slate-800/50">
                  <span className="text-slate-500">Document ID:</span>
                  <span className="text-slate-300">{selectedSource.document_id}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-800/50">
                  <span className="text-slate-500">Match Score:</span>
                  <span className="text-emerald-400 font-bold">
                    {(selectedSource.score * 100).toFixed(2)}%
                  </span>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase font-semibold text-slate-400">
                  Raw Document Chunk Content
                </label>
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-md text-xs text-slate-300 font-mono leading-relaxed max-h-96 overflow-y-auto whitespace-pre-wrap">
                  {selectedSource.content || "Chunk content preview unavailable."}
                </div>
              </div>
            </div>

            <button
              onClick={() => setSelectedSource(null)}
              className="w-full py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white text-xs font-medium rounded-md transition-all"
            >
              Close Drawer
            </button>
          </div>
        </div>
      )}
    </div>
  );
}