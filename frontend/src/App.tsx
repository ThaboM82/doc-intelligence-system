import React, { useCallback, useEffect, useState } from 'react';
import {
  ShieldCheck,
  FileText,
  MessageSquareText,
  ShieldAlert,
  Cpu,
  Activity,
  X,
  Wifi,
  WifiOff,
  Database,
  RefreshCw,
} from 'lucide-react';
import DocumentUpload from './components/DocumentUpload';
import RAGChat from './components/RAGChat';
import SecurityDashboard from './components/SecurityDashboard';
import apiClient from './lib/apiClient';
import './App.css';

type TabId = 'chat' | 'upload' | 'security';

type Notification = {
  message: string;
  type: 'success' | 'error' | 'warn' | 'info';
};

type HealthSnapshot = {
  status?: string;
  qdrant_ok?: boolean;
  collection_ready?: boolean;
  uptime_seconds?: number;
  total_requests?: number;
  reachable: boolean;
};

const TABS: { id: TabId; label: string; short: string; icon: React.ReactNode }[] = [
  { id: 'chat', label: 'RAG Chat', short: 'Chat', icon: <MessageSquareText className="w-4 h-4" /> },
  { id: 'upload', label: 'Upload Docs', short: 'Upload', icon: <FileText className="w-4 h-4" /> },
  { id: 'security', label: 'Security & Telemetry', short: 'Security', icon: <ShieldAlert className="w-4 h-4" /> },
];

function formatUptime(sec?: number) {
  if (sec == null || Number.isNaN(sec)) return '—';
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function StatusDot({
  state,
}: {
  state: 'ok' | 'warn' | 'bad' | 'unknown';
}) {
  const color =
    state === 'ok'
      ? 'bg-emerald-500'
      : state === 'warn'
        ? 'bg-amber-500'
        : state === 'bad'
          ? 'bg-rose-500'
          : 'bg-slate-300';
  const pulse = state === 'ok' ? 'animate-pulse' : '';
  return <span className={`w-2 h-2 rounded-full ${color} ${pulse}`} />;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('chat');
  const [systemNotification, setSystemNotification] = useState<Notification | null>(null);
  const [health, setHealth] = useState<HealthSnapshot>({ reachable: false });
  const [healthLoading, setHealthLoading] = useState(true);

  const apiBase =
    (typeof import.meta !== 'undefined' &&
      (import.meta as ImportMeta & { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL) ||
    (apiClient as { defaults?: { baseURL?: string }; baseURL?: string })?.defaults?.baseURL ||
    (apiClient as { baseURL?: string })?.baseURL ||
    'http://localhost:8000';

  const triggerNotification = useCallback(
    (message: string, type: Notification['type'] = 'success') => {
      setSystemNotification({ message, type });
      window.clearTimeout((triggerNotification as { _t?: number })._t);
      (triggerNotification as { _t?: number })._t = window.setTimeout(() => {
        setSystemNotification(null);
      }, 4500);
    },
    []
  );

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      // Prefer axios-style client
      let data: Record<string, unknown>;
      if (typeof (apiClient as { get?: unknown }).get === 'function') {
        const res = await (apiClient as { get: (url: string, cfg?: object) => Promise<{ data: Record<string, unknown> }> }).get(
          '/health',
          { timeout: 12_000 }
        );
        data = res.data;
      } else if (typeof (apiClient as { getHealth?: unknown }).getHealth === 'function') {
        data = (await (apiClient as { getHealth: () => Promise<Record<string, unknown>> }).getHealth()) as Record<string, unknown>;
      } else {
        const res = await fetch(`${String(apiBase).replace(/\/$/, '')}/health`);
        data = await res.json();
      }

      setHealth({
        status: String(data.status ?? 'unknown'),
        qdrant_ok: Boolean(data.qdrant_ok),
        collection_ready: Boolean(data.collection_ready),
        uptime_seconds: typeof data.uptime_seconds === 'number' ? data.uptime_seconds : undefined,
        total_requests: typeof data.total_requests === 'number' ? data.total_requests : undefined,
        reachable: true,
      });
    } catch {
      setHealth({ reachable: false, status: 'unreachable' });
    } finally {
      setHealthLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    void refreshHealth();
    const id = window.setInterval(() => void refreshHealth(), 30_000);
    return () => window.clearInterval(id);
  }, [refreshHealth]);

  const qdrantState: 'ok' | 'warn' | 'bad' | 'unknown' = !health.reachable
    ? 'bad'
    : health.qdrant_ok
      ? 'ok'
      : 'warn';

  const collectionState: 'ok' | 'warn' | 'bad' | 'unknown' = !health.reachable
    ? 'bad'
    : health.collection_ready
      ? 'ok'
      : 'warn';

  const apiState: 'ok' | 'warn' | 'bad' | 'unknown' = health.reachable
    ? health.status === 'ok'
      ? 'ok'
      : 'warn'
    : 'bad';

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 flex-shrink-0">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <h1 className="font-bold text-slate-900 tracking-tight text-base sm:text-lg truncate">
                  Doc Intelligence &amp; Security
                </h1>
                <span className="hidden sm:inline-block text-[10px] font-semibold bg-blue-50 text-blue-600 border border-blue-200 px-2 py-0.5 rounded-full">
                  v0.1.2
                </span>
              </div>
              <p className="text-xs text-slate-500 truncate">
                RAG · Docling · Threat detection
              </p>
            </div>
          </div>

          <nav
            className="flex items-center space-x-1 bg-slate-100 p-1 rounded-xl border border-slate-200/60"
            role="tablist"
            aria-label="Primary"
          >
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center space-x-2 px-3 sm:px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  activeTab === tab.id
                    ? 'bg-white text-blue-600 shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {tab.icon}
                <span className="hidden sm:inline">{tab.label}</span>
                <span className="sm:hidden">{tab.short}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Toast */}
      {systemNotification && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 w-full mt-4">
          <div
            role="status"
            className={`p-4 rounded-xl border flex items-center justify-between gap-3 text-sm ${
              systemNotification.type === 'success'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : systemNotification.type === 'warn'
                  ? 'bg-amber-50 border-amber-200 text-amber-900'
                  : systemNotification.type === 'info'
                    ? 'bg-sky-50 border-sky-200 text-sky-900'
                    : 'bg-rose-50 border-rose-200 text-rose-800'
            }`}
          >
            <span>{systemNotification.message}</span>
            <button
              type="button"
              onClick={() => setSystemNotification(null)}
              className="p-1 rounded-md opacity-60 hover:opacity-100"
              aria-label="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {!health.reachable && !healthLoading && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 w-full mt-4">
          <div className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 text-sm flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-2">
              <WifiOff className="w-4 h-4" />
              Cannot reach API at <code className="text-xs bg-white/60 px-1 rounded">{apiBase}</code>.
              Set <code className="text-xs">VITE_API_URL</code> (Vercel) and{' '}
              <code className="text-xs">CORS_ORIGINS</code> (Render).
            </span>
            <button
              type="button"
              onClick={() => void refreshHealth()}
              className="text-xs font-semibold inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-white border border-rose-200"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-8 grid grid-cols-1 lg:grid-cols-4 gap-8">
        <main className="lg:col-span-3 space-y-6" role="tabpanel">
          {activeTab === 'chat' && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Document Q&amp;A Assistant</h2>
                  <p className="text-sm text-slate-500 mt-0.5">
                    Query your Qdrant vector store via the LangChain retrieval pipeline.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveTab('upload')}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors flex items-center space-x-1.5"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Ingest More Docs</span>
                </button>
              </div>
              <RAGChat />
            </div>
          )}

          {activeTab === 'upload' && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
                <h2 className="text-xl font-bold text-slate-900">Document Ingestion Pipeline</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  Upload → security scan → Docling layout parse → vectorize into Qdrant.
                </p>
              </div>
              <DocumentUpload
                onUploadSuccess={() => {
                  triggerNotification(
                    'Document parsed, chunked, and synced to Qdrant.',
                    'success'
                  );
                  void refreshHealth();
                }}
              />
            </div>
          )}

          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
                <h2 className="text-xl font-bold text-slate-900">Security Telemetry Dashboard</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  Policy checks, injection scans, and service health.
                </p>
              </div>
              <SecurityDashboard />
            </div>
          )}
        </main>

        <aside className="space-y-6">
          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-slate-900 text-sm flex items-center space-x-2">
                <Activity className="w-4 h-4 text-blue-600" />
                <span>Pipeline Health</span>
              </h3>
              <button
                type="button"
                onClick={() => void refreshHealth()}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-50"
                title="Refresh"
                aria-label="Refresh health"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${healthLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                <span className="text-slate-600 font-medium inline-flex items-center gap-1.5">
                  {health.reachable ? (
                    <Wifi className="w-3.5 h-3.5 text-slate-400" />
                  ) : (
                    <WifiOff className="w-3.5 h-3.5 text-rose-400" />
                  )}
                  API
                </span>
                <span className="flex items-center space-x-1 font-semibold text-slate-700">
                  <StatusDot state={apiState} />
                  <span>
                    {healthLoading
                      ? '…'
                      : health.reachable
                        ? health.status || 'online'
                        : 'Down'}
                  </span>
                </span>
              </div>

              <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                <span className="text-slate-600 font-medium inline-flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-slate-400" />
                  Vector DB (Qdrant)
                </span>
                <span className="flex items-center space-x-1 font-semibold text-slate-700">
                  <StatusDot state={qdrantState} />
                  <span>
                    {!health.reachable
                      ? 'Unknown'
                      : health.qdrant_ok
                        ? 'Online'
                        : 'Degraded'}
                  </span>
                </span>
              </div>

              <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                <span className="text-slate-600 font-medium">Collection</span>
                <span className="flex items-center space-x-1 font-semibold text-slate-700">
                  <StatusDot state={collectionState} />
                  <span>
                    {!health.reachable
                      ? 'Unknown'
                      : health.collection_ready
                        ? 'Ready'
                        : 'Not ready'}
                  </span>
                </span>
              </div>

              <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                <span className="text-slate-600 font-medium">Uptime</span>
                <span className="font-semibold text-slate-700">
                  {formatUptime(health.uptime_seconds)}
                </span>
              </div>

              {health.total_requests != null && (
                <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                  <span className="text-slate-600 font-medium">Requests</span>
                  <span className="font-semibold text-slate-700">{health.total_requests}</span>
                </div>
              )}
            </div>

            <p className="text-[10px] text-slate-400 break-all">
              API: <code>{apiBase}</code>
            </p>
          </div>

          <div className="bg-gradient-to-br from-blue-900 to-slate-900 text-white p-6 rounded-2xl shadow-md space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm tracking-wide text-blue-200 uppercase">
                Architecture Stack
              </h3>
              <Cpu className="w-5 h-5 text-blue-400" />
            </div>
            <ul className="space-y-2 text-xs text-slate-300">
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>FastAPI on Render</span>
              </li>
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>Qdrant vector store</span>
              </li>
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>LangChain RAG pipeline</span>
              </li>
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>React + Tailwind (Vercel)</span>
              </li>
            </ul>
          </div>
        </aside>
      </div>

      <footer className="bg-white border-t border-slate-200 py-4 text-center text-xs text-slate-400">
        Doc Intelligence &amp; Security Suite &bull; FastAPI · Qdrant · Vercel
      </footer>
    </div>
  );
}