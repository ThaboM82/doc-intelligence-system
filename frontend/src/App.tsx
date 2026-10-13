import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  LayoutDashboard,
  KeyRound,
  LogOut,
} from 'lucide-react';
import DocumentUpload from './components/DocumentUpload';
import RAGChat from './components/RAGChat';
import SecurityDashboard from './components/SecurityDashboard';
import AdminDashboard from './components/AdminDashboard';
import apiClient from './lib/apiClient';
import './index.css';

type TabId = 'chat' | 'upload' | 'security' | 'admin';

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

const VALID_TABS: TabId[] = ['chat', 'upload', 'security', 'admin'];
const APP_VERSION = '0.2.0';
const AUTH_TOKEN_KEY = 'doc_intel_access_token';

function tabFromSearch(): TabId {
  try {
    const t = new URLSearchParams(window.location.search).get('tab');
    if (t && VALID_TABS.includes(t as TabId)) return t as TabId;
  } catch {
    /* ignore */
  }
  return 'chat';
}

function setTabInUrl(tab: TabId) {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('tab', tab);
    window.history.replaceState({}, '', url.toString());
  } catch {
    /* ignore */
  }
}

const TABS: { id: TabId; label: string; short: string; icon: React.ReactNode }[] = [
  { id: 'chat', label: 'RAG Chat', short: 'Chat', icon: <MessageSquareText className="w-4 h-4" /> },
  { id: 'upload', label: 'Upload Docs', short: 'Upload', icon: <FileText className="w-4 h-4" /> },
  {
    id: 'security',
    label: 'Security & Telemetry',
    short: 'Security',
    icon: <ShieldAlert className="w-4 h-4" />,
  },
  {
    id: 'admin',
    label: 'Admin',
    short: 'Admin',
    icon: <LayoutDashboard className="w-4 h-4" />,
  },
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

function StatusDot({ state }: { state: 'ok' | 'warn' | 'bad' | 'unknown' }) {
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

function readStoredToken(): string {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>(() => tabFromSearch());
  const [systemNotification, setSystemNotification] = useState<Notification | null>(null);
  const [health, setHealth] = useState<HealthSnapshot>({ reachable: false });
  const [healthLoading, setHealthLoading] = useState(true);
  const [authToken, setAuthToken] = useState(readStoredToken);
  const [tokenDraft, setTokenDraft] = useState(readStoredToken);
  const [showAuthPanel, setShowAuthPanel] = useState(false);
  const toastTimer = useRef<number | null>(null);

  const apiBase =
    (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ||
    (typeof apiClient.getBaseUrl === 'function' ? apiClient.getBaseUrl() : 'http://localhost:8000');

  // Apply token to apiClient when present
  useEffect(() => {
    const client = apiClient as {
      setAuthToken?: (t: string | null) => void;
      defaults?: { headers?: Record<string, string> };
    };
    if (typeof client.setAuthToken === 'function') {
      client.setAuthToken(authToken || null);
    } else if (client.defaults?.headers) {
      if (authToken) {
        client.defaults.headers.Authorization = `Bearer ${authToken}`;
      } else {
        delete client.defaults.headers.Authorization;
      }
    }
  }, [authToken]);

  const selectTab = useCallback((tab: TabId) => {
    setActiveTab(tab);
    setTabInUrl(tab);
  }, []);

  const triggerNotification = useCallback(
    (message: string, type: Notification['type'] = 'success') => {
      setSystemNotification({ message, type });
      if (toastTimer.current != null) {
        window.clearTimeout(toastTimer.current);
      }
      toastTimer.current = window.setTimeout(() => {
        setSystemNotification(null);
        toastTimer.current = null;
      }, 4500);
    },
    []
  );

  const saveToken = () => {
    const t = tokenDraft.trim();
    setAuthToken(t);
    try {
      if (t) localStorage.setItem(AUTH_TOKEN_KEY, t);
      else localStorage.removeItem(AUTH_TOKEN_KEY);
    } catch {
      /* ignore */
    }
    setShowAuthPanel(false);
    triggerNotification(t ? 'API token saved for this browser.' : 'Token cleared.', 'info');
  };

  const clearToken = () => {
    setAuthToken('');
    setTokenDraft('');
    try {
      localStorage.removeItem(AUTH_TOKEN_KEY);
    } catch {
      /* ignore */
    }
    triggerNotification('Signed out (token removed).', 'info');
  };

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = (await apiClient.getHealth()) as Record<string, unknown>;
      setHealth({
        status: String(data.status ?? 'unknown'),
        qdrant_ok: Boolean(data.qdrant_ok),
        collection_ready: Boolean(data.collection_ready),
        uptime_seconds:
          typeof data.uptime_seconds === 'number' ? data.uptime_seconds : undefined,
        total_requests:
          typeof data.total_requests === 'number' ? data.total_requests : undefined,
        reachable: true,
      });
    } catch {
      setHealth({ reachable: false, status: 'unreachable' });
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const id = window.setInterval(() => void refreshHealth(), 30_000);
    return () => {
      window.clearInterval(id);
      if (toastTimer.current != null) window.clearTimeout(toastTimer.current);
    };
  }, [refreshHealth]);

  useEffect(() => {
    const onPop = () => setActiveTab(tabFromSearch());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

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

  const shellDark = activeTab === 'security' || activeTab === 'admin';

  return (
    <div
      className={`min-h-screen flex flex-col font-sans transition-colors ${
        shellDark ? 'bg-slate-950 text-slate-100' : 'bg-slate-50 text-slate-900'
      }`}
    >
      <header
        className={`sticky top-0 z-50 border-b ${
          shellDark
            ? 'bg-slate-900/90 border-slate-800 backdrop-blur'
            : 'bg-white border-slate-200 shadow-xs'
        }`}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20 flex-shrink-0">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <h1
                  className={`font-bold tracking-tight text-base sm:text-lg truncate ${
                    shellDark ? 'text-white' : 'text-slate-900'
                  }`}
                >
                  Doc Intelligence &amp; Security
                </h1>
                <span className="hidden sm:inline-block text-[10px] font-semibold bg-blue-50 text-blue-600 border border-blue-200 px-2 py-0.5 rounded-full">
                  v{APP_VERSION}
                </span>
              </div>
              <p className={`text-xs truncate ${shellDark ? 'text-slate-400' : 'text-slate-500'}`}>
                RAG · Ingest · Threat detection · Admin
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <nav
              className={`flex items-center space-x-1 p-1 rounded-xl border overflow-x-auto max-w-[55vw] sm:max-w-none ${
                shellDark
                  ? 'bg-slate-800/80 border-slate-700'
                  : 'bg-slate-100 border-slate-200/60'
              }`}
              role="tablist"
              aria-label="Primary"
            >
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => selectTab(tab.id)}
                  className={`flex items-center space-x-2 px-2.5 sm:px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
                    activeTab === tab.id
                      ? shellDark
                        ? 'bg-slate-700 text-blue-300 shadow-xs'
                        : 'bg-white text-blue-600 shadow-xs'
                      : shellDark
                        ? 'text-slate-400 hover:text-white'
                        : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {tab.icon}
                  <span className="hidden md:inline">{tab.label}</span>
                  <span className="md:hidden">{tab.short}</span>
                </button>
              ))}
            </nav>

            <button
              type="button"
              onClick={() => setShowAuthPanel((v) => !v)}
              className={`p-2 rounded-xl border text-sm ${
                shellDark
                  ? 'border-slate-700 text-slate-300 hover:bg-slate-800'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              } ${authToken ? 'ring-1 ring-emerald-500/40' : ''}`}
              title="API bearer token"
              aria-label="Auth token"
            >
              <KeyRound className="w-4 h-4" />
            </button>
          </div>
        </div>

        {showAuthPanel && (
          <div
            className={`border-t px-4 sm:px-6 py-3 ${
              shellDark ? 'bg-slate-900 border-slate-800' : 'bg-slate-50 border-slate-200'
            }`}
          >
            <div className="max-w-7xl mx-auto flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
              <input
                type="password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="Paste JWT access_token from POST /api/v1/auth/login"
                className={`flex-1 px-3 py-2 rounded-lg text-sm border ${
                  shellDark
                    ? 'bg-slate-950 border-slate-700 text-slate-100'
                    : 'bg-white border-slate-200 text-slate-900'
                }`}
              />
              <button
                type="button"
                onClick={saveToken}
                className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold"
              >
                Save token
              </button>
              <button
                type="button"
                onClick={clearToken}
                className={`px-3 py-2 rounded-lg text-sm inline-flex items-center gap-1 border ${
                  shellDark ? 'border-slate-700 text-slate-300' : 'border-slate-200 text-slate-600'
                }`}
              >
                <LogOut className="w-3.5 h-3.5" />
                Clear
              </button>
            </div>
          </div>
        )}
      </header>

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
              Cannot reach API at{' '}
              <code className="text-xs bg-white/60 px-1 rounded">{apiBase}</code>. Set{' '}
              <code className="text-xs">VITE_API_URL</code> and{' '}
              <code className="text-xs">CORS_ORIGINS</code>.
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
                    Query Qdrant via the RAG retrieval pipeline.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => selectTab('upload')}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold transition-colors flex items-center space-x-1.5"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Ingest more docs</span>
                </button>
              </div>
              <RAGChat />
            </div>
          )}

          {activeTab === 'upload' && (
            <div className="space-y-6">
              <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs">
                <h2 className="text-xl font-bold text-slate-900">Document ingestion</h2>
                <p className="text-sm text-slate-500 mt-0.5">
                  Upload → security scan → chunk → embed → Qdrant.
                </p>
              </div>
              <DocumentUpload
                onUploadSuccess={(data?: { status?: string; message?: string }) => {
                  const st = data?.status;
                  if (st === 'quarantined') {
                    triggerNotification(
                      data?.message || 'Document quarantined by security scan.',
                      'warn'
                    );
                  } else if (st === 'failed') {
                    triggerNotification(data?.message || 'Ingest failed.', 'error');
                  } else {
                    triggerNotification(
                      data?.message || 'Document indexed into Qdrant.',
                      'success'
                    );
                  }
                  void refreshHealth();
                }}
              />
            </div>
          )}

          {activeTab === 'security' && (
            <div className="space-y-4">
              <SecurityDashboard />
            </div>
          )}

          {activeTab === 'admin' && (
            <div className="space-y-4">
              {!authToken && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-100 text-sm px-4 py-3">
                  Admin APIs need a JWT. Open the key icon, paste a token from{' '}
                  <code className="text-xs">POST /api/v1/auth/login</code>, then refresh.
                </div>
              )}
              <AdminDashboard />
            </div>
          )}
        </main>

        <aside className="space-y-6">
          <div
            className={`p-6 rounded-2xl border shadow-xs space-y-4 ${
              shellDark
                ? 'bg-slate-900/80 border-slate-800 text-slate-100'
                : 'bg-white border-slate-200'
            }`}
          >
            <div className="flex items-center justify-between">
              <h3
                className={`font-semibold text-sm flex items-center space-x-2 ${
                  shellDark ? 'text-white' : 'text-slate-900'
                }`}
              >
                <Activity className="w-4 h-4 text-blue-600" />
                <span>Pipeline health</span>
              </h3>
              <button
                type="button"
                onClick={() => void refreshHealth()}
                className={`p-1.5 rounded-lg ${
                  shellDark
                    ? 'text-slate-400 hover:text-white hover:bg-slate-800'
                    : 'text-slate-400 hover:text-slate-700 hover:bg-slate-50'
                }`}
                title="Refresh"
                aria-label="Refresh health"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${healthLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div
                className={`flex items-center justify-between p-2.5 rounded-xl border ${
                  shellDark ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-50 border-slate-100'
                }`}
              >
                <span
                  className={`font-medium inline-flex items-center gap-1.5 ${
                    shellDark ? 'text-slate-400' : 'text-slate-600'
                  }`}
                >
                  {health.reachable ? (
                    <Wifi className="w-3.5 h-3.5 text-slate-400" />
                  ) : (
                    <WifiOff className="w-3.5 h-3.5 text-rose-400" />
                  )}
                  API
                </span>
                <span className="flex items-center space-x-1 font-semibold">
                  <StatusDot state={apiState} />
                  <span>
                    {healthLoading ? '…' : health.reachable ? health.status || 'online' : 'Down'}
                  </span>
                </span>
              </div>

              <div
                className={`flex items-center justify-between p-2.5 rounded-xl border ${
                  shellDark ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-50 border-slate-100'
                }`}
              >
                <span
                  className={`font-medium inline-flex items-center gap-1.5 ${
                    shellDark ? 'text-slate-400' : 'text-slate-600'
                  }`}
                >
                  <Database className="w-3.5 h-3.5 text-slate-400" />
                  Vector DB
                </span>
                <span className="flex items-center space-x-1 font-semibold">
                  <StatusDot state={qdrantState} />
                  <span>
                    {!health.reachable ? 'Unknown' : health.qdrant_ok ? 'Online' : 'Degraded'}
                  </span>
                </span>
              </div>

              <div
                className={`flex items-center justify-between p-2.5 rounded-xl border ${
                  shellDark ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-50 border-slate-100'
                }`}
              >
                <span className={shellDark ? 'text-slate-400 font-medium' : 'text-slate-600 font-medium'}>
                  Collection
                </span>
                <span className="flex items-center space-x-1 font-semibold">
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

              <div
                className={`flex items-center justify-between p-2.5 rounded-xl border ${
                  shellDark ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-50 border-slate-100'
                }`}
              >
                <span className={shellDark ? 'text-slate-400 font-medium' : 'text-slate-600 font-medium'}>
                  Uptime
                </span>
                <span className="font-semibold">{formatUptime(health.uptime_seconds)}</span>
              </div>

              {health.total_requests != null && (
                <div
                  className={`flex items-center justify-between p-2.5 rounded-xl border ${
                    shellDark ? 'bg-slate-950/60 border-slate-800' : 'bg-slate-50 border-slate-100'
                  }`}
                >
                  <span className={shellDark ? 'text-slate-400 font-medium' : 'text-slate-600 font-medium'}>
                    Requests
                  </span>
                  <span className="font-semibold">{health.total_requests}</span>
                </div>
              )}
            </div>

            <p className={`text-[10px] break-all ${shellDark ? 'text-slate-500' : 'text-slate-400'}`}>
              API: <code>{apiBase}</code>
              {authToken ? ' · token set' : ''}
            </p>
          </div>

          <div className="bg-gradient-to-br from-blue-900 to-slate-900 text-white p-6 rounded-2xl shadow-md space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm tracking-wide text-blue-200 uppercase">
                Architecture stack
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
                <span>RAG + file security scan</span>
              </li>
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>Auth / RBAC · Admin ops</span>
              </li>
              <li className="flex items-center space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>React + Tailwind (Vercel)</span>
              </li>
            </ul>
          </div>
        </aside>
      </div>

      <footer
        className={`border-t py-4 text-center text-xs ${
          shellDark
            ? 'bg-slate-900 border-slate-800 text-slate-500'
            : 'bg-white border-slate-200 text-slate-400'
        }`}
      >
        Doc Intelligence &amp; Security Suite &bull; FastAPI · Qdrant · Vercel · v{APP_VERSION}
      </footer>
    </div>
  );
}