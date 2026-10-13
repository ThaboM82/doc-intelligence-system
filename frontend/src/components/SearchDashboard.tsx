'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Search,
  ShieldAlert,
  Activity,
  Loader2,
  RefreshCw,
  Link2,
  Mail,
  Database,
  AlertTriangle,
} from 'lucide-react';
import {
  apiClient,
  type TelemetryEvent,
  type TelemetrySummary,
} from '../lib/apiClient';

type TabId = 'search' | 'phishing' | 'telemetry';

type CollectionStats = {
  status?: string;
  vectors_count?: number;
  points_count?: number;
  indexed_vectors_count?: number;
};

type PhishResult = {
  is_phishing?: boolean;
  risk_score?: number;
  threats_detected?: string[];
  detail?: string;
  error?: string;
  [key: string]: unknown;
};

type SearchSource = {
  title?: string;
  file_name?: string;
  score?: number;
  similarity?: number;
  text?: string;
  page?: number;
};

const TABS: { id: TabId; label: string }[] = [
  { id: 'search', label: 'Document Intelligence (RAG)' },
  { id: 'phishing', label: 'Phishing Scanner' },
  { id: 'telemetry', label: 'System Telemetry' },
];

function severityClass(sev: string) {
  const s = (sev || '').toLowerCase();
  if (s === 'critical') return 'bg-red-100 text-red-700';
  if (s === 'high') return 'bg-orange-100 text-orange-700';
  if (s === 'medium') return 'bg-yellow-100 text-yellow-800';
  return 'bg-slate-100 text-slate-600';
}

export default function SearchDashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('search');

  // RAG
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<SearchSource[]>([]);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Phishing
  const [phishingInput, setPhishingInput] = useState('');
  const [scanType, setScanType] = useState<'url' | 'email'>('url');
  const [scanResult, setScanResult] = useState<PhishResult | null>(null);
  const [scanLoading, setScanLoading] = useState(false);

  // Telemetry
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoadingStats(true);
    setStatsError(null);
    try {
      const [collectionStats, telemetryData] = await Promise.all([
        apiClient.getCollectionStats().catch(() => ({
          status: 'offline',
          vectors_count: 0,
          points_count: 0,
        })),
        apiClient.getTelemetrySummary().catch(
          (): TelemetrySummary => ({
            total_caught: 0,
            active_threats: 0,
            events: [],
          })
        ),
      ]);
      setStats(collectionStats as CollectionStats);
      setTelemetry(telemetryData as TelemetrySummary);
    } catch (err) {
      console.error(err);
      setStatsError('Failed to load dashboard data.');
    } finally {
      setLoadingStats(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || searchLoading) return;

    setSearchLoading(true);
    setAnswer(null);
    setSources([]);
    setConfidence(null);
    setLatencyMs(null);
    setSearchError(null);

    try {
      // Prefer dedicated RAG endpoint (no dummy vectors)
      if (typeof apiClient.queryRag === 'function') {
        const data = await apiClient.queryRag({ query: q, top_k: 5 });
        setAnswer(data.answer || data.result || 'No answer returned.');
        setSources((data.sources as SearchSource[]) || []);
        setConfidence(
          typeof data.confidence_score === 'number' ? data.confidence_score : null
        );
        setLatencyMs(
          typeof data.processing_time_ms === 'number'
            ? data.processing_time_ms
            : null
        );
      } else if (typeof apiClient.queryIntelligence === 'function') {
        const data = await apiClient.queryIntelligence({ query: q, top_k: 5 });
        setAnswer(String((data as { answer?: string }).answer || JSON.stringify(data)));
      } else {
        const data = await apiClient.post<{
          answer?: string;
          sources?: SearchSource[];
          confidence_score?: number;
          processing_time_ms?: number;
        }>('/api/v1/rag/query', { query: q, top_k: 5 });
        setAnswer(data.answer || 'No answer returned.');
        setSources(data.sources || []);
        setConfidence(data.confidence_score ?? null);
        setLatencyMs(data.processing_time_ms ?? null);
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Failed to query intelligence system.';
      setSearchError(msg);
    } finally {
      setSearchLoading(false);
    }
  };

  const handlePhishingScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phishingInput.trim() || scanLoading) return;

    setScanLoading(true);
    setScanResult(null);
    try {
      const payload =
        scanType === 'url'
          ? { url: phishingInput.trim() }
          : { email_body: phishingInput.trim() };

      if (typeof apiClient.scanPhishingPayload === 'function') {
        const data = await apiClient.scanPhishingPayload(payload);
        setScanResult(data as PhishResult);
      } else {
        // Fallback: prompt scan endpoint
        const data = await apiClient.post<PhishResult>(
          '/api/v1/security/scan-prompt',
          { text: phishingInput.trim() }
        );
        setScanResult(data);
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Scan failed.';
      setScanResult({ error: msg });
    } finally {
      setScanLoading(false);
    }
  };

  const events: TelemetryEvent[] = telemetry?.events ?? [];

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-8 font-sans">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-gray-900 text-white p-6 rounded-2xl shadow-xl">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-blue-400" />
            Security &amp; Intelligence Control Center
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Threat detection, phishing analysis, and RAG document analytics.
          </p>
        </div>
        <div className="flex gap-3 flex-wrap items-center">
          <div className="bg-gray-800 px-4 py-3 rounded-xl border border-gray-700 min-w-[110px]">
            <span className="text-xs text-gray-400 block">Threats blocked</span>
            <span className="text-xl font-semibold text-emerald-400">
              {telemetry?.total_caught ?? '—'}
            </span>
          </div>
          <div className="bg-gray-800 px-4 py-3 rounded-xl border border-gray-700 min-w-[110px]">
            <span className="text-xs text-gray-400 block">Active alerts</span>
            <span className="text-xl font-semibold text-amber-400">
              {telemetry?.active_threats ?? '—'}
            </span>
          </div>
          <div className="bg-gray-800 px-4 py-3 rounded-xl border border-gray-700 min-w-[110px]">
            <span className="text-xs text-gray-400 block flex items-center gap-1">
              <Database className="w-3 h-3" /> Vectors
            </span>
            <span className="text-xl font-semibold text-sky-400">
              {stats?.points_count ?? stats?.vectors_count ?? '—'}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loadingStats}
            className="p-2.5 rounded-xl bg-gray-800 border border-gray-700 hover:bg-gray-750 text-gray-300"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loadingStats ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {statsError && (
        <div className="flex items-center gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <AlertTriangle className="w-4 h-4" />
          {statsError}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-200 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`pb-3 px-6 font-medium text-sm transition-colors border-b-2 whitespace-nowrap ${
              activeTab === tab.id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* RAG */}
      {activeTab === 'search' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
              <Search className="w-5 h-5 text-blue-600" />
              Query knowledge base
            </h3>
            <p className="text-sm text-gray-500">
              Vector search over Qdrant with LLM synthesis — no dummy embeddings.
            </p>
          </div>
          <form onSubmit={(e) => void handleSearch(e)} className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. What are the data retention requirements?"
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={searchLoading}
            />
            <button
              type="submit"
              disabled={searchLoading || !query.trim()}
              className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition inline-flex items-center justify-center gap-2"
            >
              {searchLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Searching…
                </>
              ) : (
                'Run query'
              )}
            </button>
          </form>

          {searchError && (
            <div className="p-4 rounded-xl border border-red-200 bg-red-50 text-red-800 text-sm">
              {searchError}
            </div>
          )}

          {answer && (
            <div className="p-5 bg-gray-50 rounded-xl border border-gray-200 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
                  Synthesized answer
                </h4>
                <div className="text-xs text-gray-400 flex gap-3">
                  {confidence != null && (
                    <span>Confidence {(confidence * 100).toFixed(0)}%</span>
                  )}
                  {latencyMs != null && <span>{latencyMs} ms</span>}
                </div>
              </div>
              <p className="text-gray-900 whitespace-pre-wrap leading-relaxed">{answer}</p>

              {sources.length > 0 && (
                <div className="pt-3 border-t border-gray-200">
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Sources</p>
                  <ul className="space-y-2">
                    {sources.map((s, i) => (
                      <li
                        key={i}
                        className="text-xs bg-white border border-gray-200 rounded-lg px-3 py-2"
                      >
                        <span className="font-medium text-gray-800">
                          {s.title || s.file_name || `Source ${i + 1}`}
                        </span>
                        {(s.score != null || s.similarity != null) && (
                          <span className="text-gray-400 ml-2">
                            {(Number(s.score ?? s.similarity) * 100).toFixed(0)}%
                          </span>
                        )}
                        {s.page != null && (
                          <span className="text-gray-400 ml-1">(p. {s.page})</span>
                        )}
                        {s.text && (
                          <p className="text-gray-500 mt-1 line-clamp-2">{s.text}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Phishing */}
      {activeTab === 'phishing' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Threat &amp; phishing detector</h3>
              <p className="text-sm text-gray-500">
                Analyze URLs or email bodies for malicious indicators.
              </p>
            </div>
            <div className="flex bg-gray-100 p-1 rounded-lg">
              <button
                type="button"
                onClick={() => setScanType('url')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition inline-flex items-center gap-1 ${
                  scanType === 'url' ? 'bg-white shadow text-blue-600' : 'text-gray-600'
                }`}
              >
                <Link2 className="w-3.5 h-3.5" /> Scan URL
              </button>
              <button
                type="button"
                onClick={() => setScanType('email')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition inline-flex items-center gap-1 ${
                  scanType === 'email' ? 'bg-white shadow text-blue-600' : 'text-gray-600'
                }`}
              >
                <Mail className="w-3.5 h-3.5" /> Scan email
              </button>
            </div>
          </div>

          <form onSubmit={(e) => void handlePhishingScan(e)} className="space-y-4">
            {scanType === 'url' ? (
              <input
                type="text"
                value={phishingInput}
                onChange={(e) => setPhishingInput(e.target.value)}
                placeholder="https://suspicious-login-domain.com"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <textarea
                rows={4}
                value={phishingInput}
                onChange={(e) => setPhishingInput(e.target.value)}
                placeholder="Paste email headers or message body…"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}
            <button
              type="submit"
              disabled={scanLoading || !phishingInput.trim()}
              className="px-6 py-3 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition inline-flex items-center gap-2"
            >
              {scanLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Analyzing…
                </>
              ) : (
                'Analyze threat'
              )}
            </button>
          </form>

          {scanResult && (
            <div className="p-5 bg-gray-50 rounded-xl border border-gray-200 space-y-3">
              <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
                Analysis results
              </h4>
              {scanResult.error ? (
                <p className="text-sm text-red-700">{scanResult.error}</p>
              ) : (
                <div className="grid sm:grid-cols-3 gap-3 text-sm">
                  <div className="bg-white border rounded-lg p-3">
                    <p className="text-xs text-gray-500">Risk</p>
                    <p className="font-semibold">
                      {scanResult.risk_score != null
                        ? Number(scanResult.risk_score).toFixed(2)
                        : '—'}
                    </p>
                  </div>
                  <div className="bg-white border rounded-lg p-3">
                    <p className="text-xs text-gray-500">Phishing</p>
                    <p className="font-semibold">
                      {scanResult.is_phishing == null
                        ? '—'
                        : scanResult.is_phishing
                          ? 'Likely'
                          : 'Unlikely'}
                    </p>
                  </div>
                  <div className="bg-white border rounded-lg p-3 sm:col-span-1">
                    <p className="text-xs text-gray-500">Threats</p>
                    <p className="font-semibold text-xs">
                      {(scanResult.threats_detected || []).join(', ') || 'None listed'}
                    </p>
                  </div>
                </div>
              )}
              <pre className="text-xs bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto max-h-48">
                {JSON.stringify(scanResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Telemetry */}
      {activeTab === 'telemetry' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
                <Activity className="w-5 h-5 text-blue-600" />
                Recent telemetry events
              </h3>
              <p className="text-sm text-gray-500">
                Intercepted threats and collection health.
              </p>
            </div>
            <p className="text-xs text-gray-400">
              Collection: {stats?.status ?? '—'} · points{' '}
              {stats?.points_count ?? stats?.vectors_count ?? '—'}
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[640px]">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Threat type</th>
                  <th className="py-3 px-4">Source IP</th>
                  <th className="py-3 px-4">Severity</th>
                  <th className="py-3 px-4">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-sm">
                {events.length > 0 ? (
                  events.map((ev, idx) => (
                    <tr key={`${ev.timestamp}-${idx}`} className="hover:bg-gray-50">
                      <td className="py-3 px-4 text-gray-600 font-mono text-xs">
                        {ev.timestamp}
                      </td>
                      <td className="py-3 px-4 font-medium text-gray-900">
                        {ev.threat_type}
                      </td>
                      <td className="py-3 px-4 font-mono text-xs text-gray-500">
                        {ev.source_ip}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2.5 py-1 text-xs rounded-full font-medium ${severityClass(
                            ev.severity
                          )}`}
                        >
                          {ev.severity}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-gray-600">
                        {(Number(ev.confidence_score || 0) * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-gray-400">
                      {loadingStats
                        ? 'Loading telemetry feed…'
                        : 'No recent threat events recorded.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}