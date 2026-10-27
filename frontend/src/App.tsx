/**
 * App — Doc Intelligence shell (auth, tabs, health, toasts).
 * Drop into: frontend/src/App.tsx
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  Menu,
  Clock,
  AlertTriangle,
} from "lucide-react";
import DocumentUpload from "./components/DocumentUpload";
import RAGChat from "./components/Chat/RAGChat";
import AdminDashboard from "./components/AdminDashboard";
import LoginForm from "./components/LoginForm";
import DocumentManager from "./components/enterprise/DocumentManager";
import apiClient from "./lib/apiClient";
import "./index.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabId = "chat" | "upload" | "security" | "admin";

type Notification = {
  id: string;
  message: string;
  type: "success" | "error" | "warn" | "info";
};

type HealthSnapshot = {
  status?: string;
  qdrant_ok?: boolean;
  collection_ready?: boolean;
  uptime_seconds?: number;
  total_requests?: number;
  memory_usage_mb?: number | null;
  cpu_percent?: number | null;
  reachable: boolean;
  checkedAt?: number;
  error?: string;
};

type UploadSuccessPayload = {
  document_id?: string;
  filename?: string;
  status?: string;
  message?: string;
  chunks_upserted?: number;
  security_scan_passed?: boolean;
};

function SecurityDashboard() {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-6 text-slate-100">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <ShieldAlert className="h-5 w-5" />
        Security &amp; Telemetry
      </h2>
      <p className="mt-2 text-sm text-slate-400">
        Security dashboard is unavailable. Restore the component in
        <code className="ml-1">src/components</code> to enable telemetry.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VALID_TABS: TabId[] = ["chat", "upload", "security", "admin"];
const APP_VERSION = "0.2.4";
const AUTH_TOKEN_KEY = "doc_intel_access_token";
const AUTH_TOKEN_LEGACY = "auth_token";
const AUTH_TOKEN_LEGACY_2 = "doc_intelligence_token";
const LIBRARY_KEY = "doc_intel_library_v1";
const HEALTH_INTERVAL_MS = 30_000;
const TOAST_MS = 4500;
const MAX_TOASTS = 4;

const TABS: {
  id: TabId;
  label: string;
  short: string;
  icon: React.ReactNode;
  description: string;
}[] = [
  {
    id: "chat",
    label: "RAG Chat",
    short: "Chat",
    icon: <MessageSquareText className="h-4 w-4" />,
    description: "Query indexed documents",
  },
  {
    id: "upload",
    label: "Upload Docs",
    short: "Upload",
    icon: <FileText className="h-4 w-4" />,
    description: "Ingest & manage files",
  },
  {
    id: "security",
    label: "Security & Telemetry",
    short: "Security",
    icon: <ShieldAlert className="h-4 w-4" />,
    description: "Threats & metrics",
  },
  {
    id: "admin",
    label: "Admin",
    short: "Admin",
    icon: <LayoutDashboard className="h-4 w-4" />,
    description: "Ops & configuration",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function tabFromSearch(): TabId {
  try {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t && VALID_TABS.includes(t as TabId)) return t as TabId;
  } catch {
    /* ignore */
  }
  return "chat";
}

function setTabInUrl(tab: TabId) {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", url.toString());
  } catch {
    /* ignore */
  }
}

function formatUptime(sec?: number) {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function formatCheckedAt(ts?: number) {
  if (!ts) return "Never";
  const ago = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (ago < 5) return "Just now";
  if (ago < 60) return `${ago}s ago`;
  if (ago < 3600) return `${Math.floor(ago / 60)}m ago`;
  return new Date(ts).toLocaleTimeString();
}

function StatusDot({ state }: { state: "ok" | "warn" | "bad" | "unknown" }) {
  const color =
    state === "ok"
      ? "bg-emerald-500"
      : state === "warn"
        ? "bg-amber-500"
        : state === "bad"
          ? "bg-rose-500"
          : "bg-slate-300";
  const pulse = state === "ok" ? "animate-pulse" : "";
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${color} ${pulse}`}
      aria-hidden
    />
  );
}

function readStoredToken(): string {
  try {
    return (
      localStorage.getItem(AUTH_TOKEN_KEY) ||
      localStorage.getItem(AUTH_TOKEN_LEGACY) ||
      localStorage.getItem(AUTH_TOKEN_LEGACY_2) ||
      ""
    );
  } catch {
    return "";
  }
}

function applyClientToken(token: string | null) {
  if (typeof apiClient.setAuthToken === "function") {
    apiClient.setAuthToken(token);
    return;
  }
  const client = apiClient as {
    defaults?: { headers?: Record<string, string> };
  };
  if (client.defaults?.headers) {
    if (token) client.defaults.headers.Authorization = `Bearer ${token}`;
    else delete client.defaults.headers.Authorization;
  }
}

function newToastId() {
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function toastTone(type: Notification["type"]) {
  switch (type) {
    case "success":
      return "border-emerald-200 bg-emerald-50 text-emerald-800";
    case "warn":
      return "border-amber-200 bg-amber-50 text-amber-900";
    case "info":
      return "border-sky-200 bg-sky-50 text-sky-900";
    default:
      return "border-rose-200 bg-rose-50 text-rose-800";
  }
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [authToken, setAuthToken] = useState(readStoredToken);
  const [authed, setAuthed] = useState(() =>
    Boolean(readStoredToken() || apiClient.getAuthToken?.())
  );
  const [activeTab, setActiveTab] = useState<TabId>(() => tabFromSearch());
  const [toasts, setToasts] = useState<Notification[]>([]);
  const [health, setHealth] = useState<HealthSnapshot>({ reachable: false });
  const [healthLoading, setHealthLoading] = useState(true);
  const [tokenDraft, setTokenDraft] = useState(readStoredToken);
  const [showAuthPanel, setShowAuthPanel] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const toastTimers = useRef<Map<string, number>>(new Map());
  const authPanelRef = useRef<HTMLDivElement | null>(null);
  const authButtonRef = useRef<HTMLButtonElement | null>(null);

  const apiBase =
    (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ||
    (typeof apiClient.getBaseUrl === "function"
      ? apiClient.getBaseUrl()
      : "http://localhost:8000");

  useEffect(() => {
    applyClientToken(authToken || null);
  }, [authToken]);

  useEffect(() => {
    if (typeof apiClient.setUnauthorizedHandler === "function") {
      apiClient.setUnauthorizedHandler(() => {
        persistToken("");
        setAuthed(false);
        pushToast("Session expired. Please sign in again.", "warn");
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectTab = useCallback((tab: TabId) => {
    setActiveTab(tab);
    setTabInUrl(tab);
    setMobileNavOpen(false);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = toastTimers.current.get(id);
    if (timer != null) {
      window.clearTimeout(timer);
      toastTimers.current.delete(id);
    }
  }, []);

  const pushToast = useCallback(
    (message: string, type: Notification["type"] = "success") => {
      const id = newToastId();
      setToasts((prev) => {
        const next = [...prev, { id, message, type }];
        return next.slice(-MAX_TOASTS);
      });
      const timer = window.setTimeout(() => {
        dismissToast(id);
      }, TOAST_MS);
      toastTimers.current.set(id, timer);
    },
    [dismissToast]
  );

  const persistToken = useCallback((t: string) => {
    setAuthToken(t);
    setTokenDraft(t);
    setAuthed(Boolean(t));
    try {
      if (t) {
        localStorage.setItem(AUTH_TOKEN_KEY, t);
        localStorage.setItem(AUTH_TOKEN_LEGACY, t);
      } else {
        localStorage.removeItem(AUTH_TOKEN_KEY);
        localStorage.removeItem(AUTH_TOKEN_LEGACY);
        localStorage.removeItem(AUTH_TOKEN_LEGACY_2);
      }
    } catch {
      /* ignore */
    }
    applyClientToken(t || null);
  }, []);

  const saveToken = () => {
    const t = tokenDraft.trim();
    persistToken(t);
    setShowAuthPanel(false);
    pushToast(
      t ? "API token saved for this browser." : "Token cleared.",
      "info"
    );
  };

  const signOut = () => {
    persistToken("");
    setShowAuthPanel(false);
    setMobileNavOpen(false);
    setAuthed(false);
    pushToast("Signed out.", "info");
  };

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = (await apiClient.getHealth()) as Record<string, unknown>;
      setHealth({
        status: String(data.status ?? "unknown"),
        qdrant_ok: Boolean(data.qdrant_ok),
        collection_ready: Boolean(data.collection_ready),
        uptime_seconds:
          typeof data.uptime_seconds === "number"
            ? data.uptime_seconds
            : undefined,
        total_requests:
          typeof data.total_requests === "number"
            ? data.total_requests
            : undefined,
        memory_usage_mb:
          typeof data.memory_usage_mb === "number"
            ? data.memory_usage_mb
            : null,
        cpu_percent:
          typeof data.cpu_percent === "number" ? data.cpu_percent : null,
        reachable: true,
        checkedAt: Date.now(),
      });
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : typeof (err as { message?: unknown })?.message === "string"
            ? String((err as { message: string }).message)
            : "Health check failed";
      setHealth({
        reachable: false,
        status: "unreachable",
        checkedAt: Date.now(),
        error: msg,
      });
    } finally {
      setHealthLoading(false);
    }
  }, []);
    useEffect(() => {
    if (!authed) return;
    void refreshHealth();
    const id = window.setInterval(
      () => void refreshHealth(),
      HEALTH_INTERVAL_MS
    );
    return () => {
      window.clearInterval(id);
      toastTimers.current.forEach((t) => window.clearTimeout(t));
      toastTimers.current.clear();
    };
  }, [authed, refreshHealth]);

  useEffect(() => {
    const onPop = () => setActiveTab(tabFromSearch());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Escape closes panels; Alt+1..4 switches tabs
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowAuthPanel(false);
        setMobileNavOpen(false);
      }
      if (e.altKey && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
        const map: Record<string, TabId> = {
          "1": "chat",
          "2": "upload",
          "3": "security",
          "4": "admin",
        };
        const tab = map[e.key];
        if (tab) {
          e.preventDefault();
          selectTab(tab);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectTab]);

  // Click outside auth panel
  useEffect(() => {
    if (!showAuthPanel) return;
    const onPointer = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        authPanelRef.current?.contains(target) ||
        authButtonRef.current?.contains(target)
      ) {
        return;
      }
      setShowAuthPanel(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [showAuthPanel]);

  const onUploadSuccess = useCallback(
    (data?: UploadSuccessPayload) => {
      try {
        if (data?.document_id && data?.filename) {
          const prev = JSON.parse(
            localStorage.getItem(LIBRARY_KEY) || "[]"
          ) as unknown[];
          const list = Array.isArray(prev) ? prev : [];
          const next = [
            {
              document_id: data.document_id,
              filename: data.filename,
              status: data.status || "unknown",
              chunks_upserted: data.chunks_upserted,
              security_scan_passed: data.security_scan_passed,
              message: data.message,
              uploaded_at: Date.now(),
            },
            ...list.filter(
              (d) =>
                (d as { document_id?: string }).document_id !== data.document_id
            ),
          ].slice(0, 50);
          localStorage.setItem(LIBRARY_KEY, JSON.stringify(next));
          window.dispatchEvent(new Event("doc-library-updated"));
        }
      } catch {
        /* ignore */
      }

      const st = (data?.status || "").toLowerCase();
      const name = data?.filename ? ` (${data.filename})` : "";

      if (st === "quarantined") {
        pushToast(
          data?.message || `Document quarantined by security scan${name}.`,
          "warn"
        );
      } else if (st === "failed") {
        pushToast(data?.message || `Ingest failed${name}.`, "error");
      } else if (!data?.document_id && st === "failed") {
        pushToast(data?.message || "Upload failed.", "error");
      } else {
        const chunks =
          data?.chunks_upserted != null
            ? ` · ${data.chunks_upserted} chunks`
            : "";
        pushToast(
          data?.message || `Document indexed into Qdrant${name}${chunks}.`,
          "success"
        );
      }
      void refreshHealth();
    },
    [pushToast, refreshHealth]
  );

  const activeTabMeta = useMemo(
    () => TABS.find((t) => t.id === activeTab),
    [activeTab]
  );

  if (!authed) {
    return (
      <LoginForm
        onLoginSuccess={(token?: string) => {
          const t = token || readStoredToken() || "session";
          persistToken(t);
          setAuthed(true);
          pushToast("Signed in.", "success");
        }}
      />
    );
  }

  const qdrantState: "ok" | "warn" | "bad" | "unknown" = !health.reachable
    ? "bad"
    : health.qdrant_ok
      ? "ok"
      : "warn";
  const collectionState: "ok" | "warn" | "bad" | "unknown" = !health.reachable
    ? "bad"
    : health.collection_ready
      ? "ok"
      : "warn";
  const apiState: "ok" | "warn" | "bad" | "unknown" = health.reachable
    ? health.status === "ok"
      ? "ok"
      : "warn"
    : "bad";

  const shellDark = activeTab === "security" || activeTab === "admin";
  const shellBg = shellDark
    ? "bg-slate-950 text-slate-100"
    : "bg-slate-50 text-slate-900";
  const headerBg = shellDark
    ? "bg-slate-900/90 border-slate-800 backdrop-blur"
    : "bg-white border-slate-200 shadow-sm";
  const muted = shellDark ? "text-slate-400" : "text-slate-500";
  const card = shellDark
    ? "bg-slate-900/80 border-slate-800"
    : "bg-white border-slate-200";

  return (
    <div
      className={`flex min-h-screen flex-col font-sans transition-colors ${shellBg}`}
    >
      {/* Header */}
      <header className={`sticky top-0 z-50 border-b ${headerBg}`}>
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              className={`rounded-xl border p-2 lg:hidden ${
                shellDark
                  ? "border-slate-700 text-slate-300"
                  : "border-slate-200 text-slate-600"
              }`}
              onClick={() => setMobileNavOpen((v) => !v)}
              aria-label="Toggle navigation"
              aria-expanded={mobileNavOpen}
            >
              <Menu className="h-4 w-4" />
            </button>

            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-500/20">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1
                  className={`truncate text-base font-bold tracking-tight sm:text-lg ${
                    shellDark ? "text-white" : "text-slate-900"
                  }`}
                >
                  Doc Intelligence &amp; Security
                </h1>
                <span className="hidden rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600 sm:inline-block">
                  v{APP_VERSION}
                </span>
              </div>
              <p className={`truncate text-xs ${muted}`}>
                RAG · Ingest · Threat detection · Admin
                {activeTabMeta ? ` · ${activeTabMeta.label}` : ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <nav
              className={`hidden max-w-none items-center gap-1 overflow-x-auto rounded-xl border p-1 sm:flex ${
                shellDark
                  ? "border-slate-700 bg-slate-800/80"
                  : "border-slate-200/60 bg-slate-100"
              }`}
              role="tablist"
              aria-label="Primary"
            >
              {TABS.map((tab, idx) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  title={`${tab.label} (Alt+${idx + 1})`}
                  onClick={() => selectTab(tab.id)}
                  className={`flex items-center gap-2 whitespace-nowrap rounded-lg px-2.5 py-2 text-sm font-medium transition-all sm:px-3 ${
                    activeTab === tab.id
                      ? shellDark
                        ? "bg-slate-700 text-blue-300 shadow-sm"
                        : "bg-white text-blue-600 shadow-sm"
                      : shellDark
                        ? "text-slate-400 hover:text-white"
                        : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {tab.icon}
                  <span className="hidden md:inline">{tab.label}</span>
                  <span className="md:hidden">{tab.short}</span>
                </button>
              ))}
            </nav>

            <button
              ref={authButtonRef}
              type="button"
              onClick={() => setShowAuthPanel((v) => !v)}
              className={`rounded-xl border p-2 text-sm ${
                shellDark
                  ? "border-slate-700 text-slate-300 hover:bg-slate-800"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              } ${authToken ? "ring-1 ring-emerald-500/40" : ""}`}
              title="API bearer token"
              aria-label="Auth token"
              aria-expanded={showAuthPanel}
            >
              <KeyRound className="h-4 w-4" />
            </button>

            <button
              type="button"
              onClick={signOut}
              className={`rounded-xl border p-2 text-sm ${
                shellDark
                  ? "border-slate-700 text-slate-300 hover:bg-slate-800"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
              title="Sign out"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Mobile nav */}
        {mobileNavOpen ? (
          <div
            className={`border-t px-4 py-2 sm:hidden ${
              shellDark
                ? "border-slate-800 bg-slate-900"
                : "border-slate-200 bg-white"
            }`}
          >
            <div className="grid grid-cols-2 gap-1">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => selectTab(tab.id)}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium ${
                    activeTab === tab.id
                      ? "bg-blue-600 text-white"
                      : shellDark
                        ? "text-slate-300 hover:bg-slate-800"
                        : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  {tab.icon}
                  {tab.short}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* Auth panel */}
        {showAuthPanel ? (
          <div
            ref={authPanelRef}
            className={`border-t px-4 py-3 sm:px-6 ${
              shellDark
                ? "border-slate-800 bg-slate-900"
                : "border-slate-200 bg-slate-50"
            }`}
          >
            <div className="mx-auto flex max-w-7xl flex-col items-stretch gap-2 sm:flex-row sm:items-center">
              <input
                type="password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveToken();
                }}
                placeholder="Paste JWT access_token from POST /api/v1/auth/login"
                className={`flex-1 rounded-lg border px-3 py-2 text-sm ${
                  shellDark
                    ? "border-slate-700 bg-slate-950 text-slate-100"
                    : "border-slate-200 bg-white text-slate-900"
                }`}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={saveToken}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
              >
                Save token
              </button>
              <button
                type="button"
                onClick={signOut}
                className={`inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm ${
                  shellDark
                    ? "border-slate-700 text-slate-300"
                    : "border-slate-200 text-slate-600"
                }`}
              >
                <LogOut className="h-3.5 w-3.5" />
                Clear / sign out
              </button>
            </div>
            <p className={`mx-auto mt-2 max-w-7xl text-[11px] ${muted}`}>
              Token is stored in this browser only. Press Esc to close.
            </p>
          </div>
        ) : null}
      </header>
            {/* Toast stack */}
      {toasts.length > 0 ? (
        <div
          className="pointer-events-none fixed right-4 top-20 z-[60] flex w-[min(100%-2rem,24rem)] flex-col gap-2"
          aria-live="polite"
        >
          {toasts.map((n) => (
            <div
              key={n.id}
              role="status"
              className={`pointer-events-auto flex items-start justify-between gap-3 rounded-xl border p-3 text-sm shadow-lg ${toastTone(
                n.type
              )}`}
            >
              <span className="min-w-0 flex-1 break-words">{n.message}</span>
              <button
                type="button"
                onClick={() => dismissToast(n.id)}
                className="shrink-0 rounded-md p-1 opacity-60 hover:opacity-100"
                aria-label="Dismiss"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {/* API down banner */}
      {!health.reachable && !healthLoading ? (
        <div className="mx-auto mt-4 w-full max-w-7xl px-4 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <span className="inline-flex items-center gap-2">
              <WifiOff className="h-4 w-4 shrink-0" />
              Cannot reach API at{" "}
              <code className="rounded bg-white/60 px-1 text-xs">{apiBase}</code>
              . Set <code className="text-xs">VITE_API_URL</code> and{" "}
              <code className="text-xs">CORS_ORIGINS</code>.
              {health.error ? (
                <span className="text-xs opacity-80">({health.error})</span>
              ) : null}
            </span>
            <button
              type="button"
              onClick={() => void refreshHealth()}
              className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-2 py-1 text-xs font-semibold"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
          </div>
        </div>
      ) : null}

      {/* Collection not ready */}
      {health.reachable &&
      health.qdrant_ok &&
      health.collection_ready === false ? (
        <div className="mx-auto mt-4 w-full max-w-7xl px-4 sm:px-6">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Vector collection is not ready. Upload documents or check Qdrant
            configuration.
          </div>
        </div>
      ) : null}

      {/* Body */}
      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-8 px-4 py-8 sm:px-6 lg:grid-cols-4">
        <main className="space-y-6 lg:col-span-3" role="tabpanel">
          {activeTab === "chat" && (
            <div className="space-y-6">
              <div className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:flex-row sm:items-center">
                <div>
                  <h2 className="text-xl font-bold text-slate-900">
                    Document Q&amp;A Assistant
                  </h2>
                  <p className="mt-0.5 text-sm text-slate-500">
                    Query Qdrant via the RAG retrieval pipeline. Answers support
                    markdown and source citations.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => selectTab("upload")}
                  className="flex items-center gap-1.5 rounded-xl bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-200"
                >
                  <FileText className="h-3.5 w-3.5" />
                  <span>Ingest more docs</span>
                </button>
              </div>
              <RAGChat />
            </div>
          )}

          {activeTab === "upload" && (
            <div className="space-y-6">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="text-xl font-bold text-slate-900">
                  Document ingestion
                </h2>
                <p className="mt-0.5 text-sm text-slate-500">
                  Upload → security scan → chunk → embed → Qdrant. Bulk
                  drag-and-drop supported.
                </p>
              </div>
              <DocumentUpload onUploadSuccess={onUploadSuccess} />
              <DocumentManager />
            </div>
          )}

          {activeTab === "security" && (
            <div className="space-y-4">
              <SecurityDashboard />
            </div>
          )}

          {activeTab === "admin" && (
            <div className="space-y-4">
              {!authToken && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                  Admin APIs need a JWT. Open the key icon, paste a token from{" "}
                  <code className="text-xs">POST /api/v1/auth/login</code>, then
                  refresh.
                </div>
              )}
              <AdminDashboard />
            </div>
          )}
        </main>

        {/* Sidebar */}
        <aside className="space-y-6">
          <div className={`space-y-4 rounded-2xl border p-6 shadow-sm ${card}`}>
            <div className="flex items-center justify-between">
              <h3
                className={`flex items-center gap-2 text-sm font-semibold ${
                  shellDark ? "text-white" : "text-slate-900"
                }`}
              >
                <Activity className="h-4 w-4 text-blue-600" />
                <span>Pipeline health</span>
              </h3>
              <button
                type="button"
                onClick={() => void refreshHealth()}
                className={`rounded-lg p-1.5 ${
                  shellDark
                    ? "text-slate-400 hover:bg-slate-800 hover:text-white"
                    : "text-slate-400 hover:bg-slate-50 hover:text-slate-700"
                }`}
                title="Refresh"
                aria-label="Refresh health"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${healthLoading ? "animate-spin" : ""}`}
                />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              {(
                [
                  {
                    label: "API",
                    icon: health.reachable ? (
                      <Wifi className="h-3.5 w-3.5 text-slate-400" />
                    ) : (
                      <WifiOff className="h-3.5 w-3.5 text-rose-400" />
                    ),
                    state: apiState,
                    value: healthLoading
                      ? "…"
                      : health.reachable
                        ? health.status || "online"
                        : "Down",
                  },
                  {
                    label: "Vector DB",
                    icon: <Database className="h-3.5 w-3.5 text-slate-400" />,
                    state: qdrantState,
                    value: !health.reachable
                      ? "Unknown"
                      : health.qdrant_ok
                        ? "Online"
                        : "Degraded",
                  },
                  {
                    label: "Collection",
                    icon: null,
                    state: collectionState,
                    value: !health.reachable
                      ? "Unknown"
                      : health.collection_ready
                        ? "Ready"
                        : "Not ready",
                  },
                ] as const
              ).map((row) => (
                <div
                  key={row.label}
                  className={`flex items-center justify-between rounded-xl border p-2.5 ${
                    shellDark
                      ? "border-slate-800 bg-slate-950/60"
                      : "border-slate-100 bg-slate-50"
                  }`}
                >
                  <span
                    className={`inline-flex items-center gap-1.5 font-medium ${
                      shellDark ? "text-slate-400" : "text-slate-600"
                    }`}
                  >
                    {row.icon}
                    {row.label}
                  </span>
                  <span className="flex items-center gap-1 font-semibold">
                    <StatusDot state={row.state} />
                    <span>{row.value}</span>
                  </span>
                </div>
              ))}

              <div
                className={`flex items-center justify-between rounded-xl border p-2.5 ${
                  shellDark
                    ? "border-slate-800 bg-slate-950/60"
                    : "border-slate-100 bg-slate-50"
                }`}
              >
                <span
                  className={
                    shellDark
                      ? "font-medium text-slate-400"
                      : "font-medium text-slate-600"
                  }
                >
                  Uptime
                </span>
                <span className="font-semibold">
                  {formatUptime(health.uptime_seconds)}
                </span>
              </div>

              {health.total_requests != null ? (
                <div
                  className={`flex items-center justify-between rounded-xl border p-2.5 ${
                    shellDark
                      ? "border-slate-800 bg-slate-950/60"
                      : "border-slate-100 bg-slate-50"
                  }`}
                >
                  <span
                    className={
                      shellDark
                        ? "font-medium text-slate-400"
                        : "font-medium text-slate-600"
                    }
                  >
                    Requests
                  </span>
                  <span className="font-semibold">{health.total_requests}</span>
                </div>
              ) : null}

              {health.memory_usage_mb != null ? (
                <div
                  className={`flex items-center justify-between rounded-xl border p-2.5 ${
                    shellDark
                      ? "border-slate-800 bg-slate-950/60"
                      : "border-slate-100 bg-slate-50"
                  }`}
                >
                  <span
                    className={
                      shellDark
                        ? "font-medium text-slate-400"
                        : "font-medium text-slate-600"
                    }
                  >
                    Memory
                  </span>
                  <span className="font-semibold">
                    {Math.round(health.memory_usage_mb)} MB
                  </span>
                </div>
              ) : null}

              <div
                className={`flex items-center justify-between rounded-xl border p-2.5 ${
                  shellDark
                    ? "border-slate-800 bg-slate-950/60"
                    : "border-slate-100 bg-slate-50"
                }`}
              >
                <span
                  className={`inline-flex items-center gap-1.5 font-medium ${
                    shellDark ? "text-slate-400" : "text-slate-600"
                  }`}
                >
                  <Clock className="h-3.5 w-3.5" />
                  Checked
                </span>
                <span className="font-semibold">
                  {formatCheckedAt(health.checkedAt)}
                </span>
              </div>
            </div>

            <p
              className={`break-all text-[10px] ${
                shellDark ? "text-slate-500" : "text-slate-400"
              }`}
            >
              API: <code>{apiBase}</code>
              {authToken ? " · token set" : " · no token"}
            </p>
          </div>

          <div className="space-y-4 rounded-2xl bg-gradient-to-br from-blue-900 to-slate-900 p-6 text-white shadow-md">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-blue-200">
                Architecture stack
              </h3>
              <Cpu className="h-5 w-5 text-blue-400" />
            </div>
            <ul className="space-y-2 text-xs text-slate-300">
              {[
                "FastAPI on Render",
                "Qdrant vector store",
                "RAG + file security scan",
                "Auth / RBAC · Admin ops",
                "React + Tailwind (Vercel)",
              ].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
            <p className="text-[10px] text-slate-500">
              Shortcuts: Alt+1–4 switch tabs · Esc close panels
            </p>
          </div>
        </aside>
      </div>

      <footer
        className={`border-t py-4 text-center text-xs ${
          shellDark
            ? "border-slate-800 bg-slate-900 text-slate-500"
            : "border-slate-200 bg-white text-slate-400"
        }`}
      >
        Doc Intelligence &amp; Security Suite · FastAPI · Qdrant · Vercel · v
        {APP_VERSION}
      </footer>
    </div>
  );
}