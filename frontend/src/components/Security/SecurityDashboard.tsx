import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Activity,
  AlertTriangle,
  RefreshCw,
  Terminal,
  Filter,
  WifiOff,
  Sparkles,
  TrendingUp,
  Download,
  Search,
  Database,
  FileJson,
  Pause,
  Play,
  Loader2,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import {
  apiClient,
  type HealthStatus,
  type TelemetryEvent,
  type TelemetrySummary,
  type CollectionStats,
} from '../lib/apiClient';

interface SecurityStats {
  totalScanned: number;
  threatsDetected: number;
  policyViolations: number;
  systemStatus: string;
  criticalCount: number;
  ragQueries: number;
}

interface SecurityLog {
  id: string;
  timestamp: string;
  filename: string;
  type: string;
  severity: string;
  status: string;
  sourceIp?: string;
}

const mockThreatTrendData = [
  { day: 'Mon', scans: 140, threats: 2 },
  { day: 'Tue', scans: 220, threats: 5 },
  { day: 'Wed', scans: 190, threats: 1 },
  { day: 'Thu', scans: 310, threats: 4 },
  { day: 'Fri', scans: 280, threats: 3 },
  { day: 'Sat', scans: 150, threats: 0 },
  { day: 'Sun', scans: 190, threats: 1 },
];

const mockRecentLogs: SecurityLog[] = [
  {
    id: 'LOG-9402',
    timestamp: '10 mins ago',
    filename: 'financial_report_Q3.pdf',
    type: 'Policy Violation',
    severity: 'Medium',
    status: 'Quarantined',
  },
  {
    id: 'LOG-9401',
    timestamp: '25 mins ago',
    filename: 'untrusted_script_payload.docx',
    type: 'Malware / Phishing Pattern',
    severity: 'High',
    status: 'Blocked',
  },
  {
    id: 'LOG-9400',
    timestamp: '1 hour ago',
    filename: 'system_architecture.md',
    type: 'Clean Ingestion',
    severity: 'Low',
    status: 'Vectorized',
  },
  {
    id: 'LOG-9399',
    timestamp: '2 hours ago',
    filename: 'external_invoice_#8821.pdf',
    type: 'Data Leakage Risk',
    severity: 'High',
    status: 'Flagged',
  },
];

function normalizeSeverity(sev: string): string {
  const s = String(sev || 'low').toLowerCase();
  if (s === 'critical') return 'Critical';
  if (s === 'high') return 'High';
  if (s === 'medium') return 'Medium';
  return 'Low';
}

function mapTelemetryToLogs(events: TelemetryEvent[]): SecurityLog[] {
  return events.map((ev, i) => {
    const severity = normalizeSeverity(String(ev.severity || 'low'));
    const high = severity === 'Critical' || severity === 'High';
    return {
      id: (ev as { id?: string }).id || `TEL-${String(i + 1).padStart(4, '0')}`,
      timestamp: ev.timestamp || '—',
      filename:
        (ev.document_id as string) ||
        (typeof ev.detail === 'string' ? ev.detail : null) ||
        ev.source_ip ||
        '—',
      type: ev.threat_type || ev.detector || 'Event',
      severity,
      status: high ? 'Blocked' : 'Logged',
      sourceIp: ev.source_ip,
    };
  });
}

function severityClass(severity: string) {
  const s = severity.toLowerCase();
  if (s === 'critical') {
    return 'bg-purple-500/15 text-purple-300 ring-1 ring-purple-500/30';
  }
  if (s === 'high') {
    return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30';
  }
  if (s === 'medium') {
    return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
  }
  return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30';
}

function downloadBlob(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportLogsCsv(logs: SecurityLog[]) {
  const header = [
    'id',
    'timestamp',
    'source',
    'type',
    'severity',
    'status',
    'source_ip',
  ];
  const rows = logs.map((l) =>
    [
      l.id,
      l.timestamp,
      l.filename,
      l.type,
      l.severity,
      l.status,
      l.sourceIp || '',
    ]
      .map((c) => `"${String(c).replace(/"/g, '""')}"`)
      .join(',')
  );
  downloadBlob(
    `security-events-${new Date().toISOString().slice(0, 10)}.csv`,
    [header.join(','), ...rows].join('\n'),
    'text/csv;charset=utf-8'
  );
}

function exportDashboardJson(payload: unknown) {
  downloadBlob(
    `security-dashboard-${Date.now()}.json`,
    JSON.stringify(
      { exported_at: new Date().toISOString(), ...(payload as object) },
      null,
      2
    ),
    'application/json'
  );
}

const cardBase =
  'relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/80 to-slate-950/90 shadow-[0_8px_32px_rgba(0,0,0,0.35)] backdrop-blur-xl';

export default function SecurityDashboard() {
  const [stats, setStats] = useState<SecurityStats>({
    totalScanned: 1480,
    threatsDetected: 16,
    policyViolations: 4,
    systemStatus: 'Secure',
    criticalCount: 0,
    ragQueries: 0,
  });
  const [logs, setLogs] = useState<SecurityLog[]>(mockRecentLogs);
  const [trendData] = useState(mockThreatTrendData);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [collection, setCollection] = useState<CollectionStats | null>(null);
  const [filterSeverity, setFilterSeverity] = useState('ALL');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [usingFallback, setUsingFallback] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [downloading, setDownloading] = useState(false);

  // Live SSE
  const [live, setLive] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // AI threat analysis
  const [aiText, setAiText] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<{
    flagged?: boolean;
    score?: number;
    severity?: string;
    rationale?: string | null;
    detector?: string;
  } | null>(null);

  const fetchSecurityData = useCallback(async () => {
    setLoading(true);
    try {
      const [healthRes, telemRes, collRes] = await Promise.allSettled([
        apiClient.getHealth(),
        apiClient.getTelemetrySummary(),
        apiClient.getCollectionStats(),
      ]);

      let gotLive = false;

      if (healthRes.status === 'fulfilled') {
        const h = healthRes.value;
        setHealth(h);
        gotLive = true;
        setStats((prev) => ({
          ...prev,
          systemStatus:
            h.status === 'ok' && h.qdrant_ok
              ? 'Secure'
              : h.status === 'ok'
                ? 'Degraded'
                : 'Alert',
        }));
      }

      if (telemRes.status === 'fulfilled') {
        const t: TelemetrySummary = telemRes.value;
        gotLive = true;
        const events = t.events || [];
        const critical = events.filter((e) =>
          ['critical', 'high'].includes(String(e.severity || '').toLowerCase())
        ).length;
        setStats((prev) => ({
          ...prev,
          totalScanned: t.scans_total ?? t.total_caught ?? prev.totalScanned,
          threatsDetected: t.active_threats ?? prev.threatsDetected,
          policyViolations:
            t.quarantine_total ??
            Math.max(
              prev.policyViolations,
              Math.floor((t.active_threats || 0) / 2)
            ),
          criticalCount: critical,
          ragQueries: t.rag_queries ?? prev.ragQueries,
        }));
        if (events.length) setLogs(mapTelemetryToLogs(events));
      }

      if (collRes.status === 'fulfilled' && collRes.value) {
        setCollection(collRes.value as CollectionStats);
        gotLive = true;
      }

      setUsingFallback(!gotLive);
      setLastSynced(new Date().toLocaleTimeString());
    } catch (err) {
      console.error('Telemetry unreachable:', err);
      setUsingFallback(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchSecurityData();
  }, [fetchSecurityData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => void fetchSecurityData(), 60_000);
    return () => window.clearInterval(id);
  }, [autoRefresh, fetchSecurityData]);

  // SSE live stream
  useEffect(() => {
    let es: EventSource | null = null;
    const streamClient = apiClient as typeof apiClient & {
      streamSecurityEvents?: (
        onMessage: (raw: string) => void,
        onError: () => void
      ) => EventSource;
    };
    try {
      if (typeof streamClient.streamSecurityEvents !== 'function') {
        setStreamError('SSE helper missing on apiClient');
        return;
      }
      es = streamClient.streamSecurityEvents(
        (raw) => {
          try {
            const ev = JSON.parse(raw) as TelemetryEvent & { id?: string };
            setLive(true);
            setStreamError(null);
            const mapped = mapTelemetryToLogs([ev])[0];
            if (!mapped) return;
            setLogs((prev) => {
              const next = [
                mapped,
                ...prev.filter((l) => l.id !== mapped.id),
              ];
              return next.slice(0, 100);
            });
            setUsingFallback(false);
          } catch {
            /* keepalive */
          }
        },
        () => {
          setLive(false);
          setStreamError('Stream disconnected — poll only');
          es?.close();
        }
      );
      esRef.current = es;
    } catch {
      setStreamError('SSE not available');
    }
    return () => {
      es?.close();
      esRef.current = null;
    };
  }, []);

  const runAiThreatAnalysis = async () => {
    const text = aiText.trim();
    if (!text || aiLoading) return;
    setAiLoading(true);
    setAiResult(null);
    try {
      const res = await apiClient.threatScan({ text, use_ai: true });
      setAiResult({
        flagged: res.flagged,
        score: res.score,
        severity: res.severity,
        rationale: res.rationale,
        detector: res.detector,
      });
      if (res.flagged) {
        setLogs((prev) =>
          [
            {
              id: `AI-${Date.now()}`,
              timestamp: new Date().toLocaleTimeString(),
              filename: 'manual-analysis',
              type: res.detector || 'AI threat scan',
              severity: normalizeSeverity(res.severity || 'medium'),
              status: 'Flagged',
            },
            ...prev,
          ].slice(0, 100)
        );
      }
    } catch (err) {
      setAiResult({
        flagged: false,
        score: 0,
        severity: 'low',
        rationale:
          err && typeof err === 'object' && 'message' in err
            ? String((err as { message: unknown }).message)
            : 'AI scan failed (check admin auth / route)',
        detector: 'error',
      });
    } finally {
      setAiLoading(false);
    }
  };

  const filteredLogs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.filter((log) => {
      if (
        filterSeverity !== 'ALL' &&
        log.severity.toUpperCase() !== filterSeverity
      ) {
        return false;
      }
      if (!q) return true;
      return (
        log.filename.toLowerCase().includes(q) ||
        log.type.toLowerCase().includes(q) ||
        log.id.toLowerCase().includes(q) ||
        log.status.toLowerCase().includes(q) ||
        (log.sourceIp || '').toLowerCase().includes(q)
      );
    });
  }, [logs, filterSeverity, search]);

  const statusColor =
    stats.systemStatus === 'Secure'
      ? 'text-emerald-400'
      : stats.systemStatus === 'Degraded'
        ? 'text-amber-400'
        : 'text-rose-400';

  const statusDot =
    stats.systemStatus === 'Secure'
      ? 'bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.6)]'
      : stats.systemStatus === 'Degraded'
        ? 'bg-amber-400 shadow-[0_0_12px_rgba(251,191,36,0.5)]'
        : 'bg-rose-400 shadow-[0_0_12px_rgba(251,113,133,0.5)]';

  const kpiCards = [
    {
      label: 'Total scanned',
      value: stats.totalScanned.toLocaleString(),
      icon: Activity,
      accent: 'from-blue-500/20 to-transparent',
      iconColor: 'text-blue-400',
      ring: 'ring-blue-500/20',
      isStatus: false,
    },
    {
      label: 'Threats flagged',
      value: String(stats.threatsDetected),
      icon: ShieldAlert,
      accent: 'from-amber-500/20 to-transparent',
      iconColor: 'text-amber-400',
      ring: 'ring-amber-500/20',
      isStatus: false,
    },
    {
      label: 'Policy / critical',
      value: `${stats.policyViolations} / ${stats.criticalCount}`,
      icon: AlertTriangle,
      accent: 'from-rose-500/20 to-transparent',
      iconColor: 'text-rose-400',
      ring: 'ring-rose-500/20',
      isStatus: false,
    },
    {
      label: 'System status',
      value: stats.systemStatus,
      icon: ShieldCheck,
      accent: 'from-emerald-500/20 to-transparent',
      iconColor: 'text-emerald-400',
      ring: 'ring-emerald-500/20',
      isStatus: true,
    },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6 text-slate-100">
      {/* Hero */}
      <div className={`${cardBase} p-6 sm:p-8`}>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(59,130,246,0.15),_transparent_50%)]" />
        <div className="relative flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="mb-2 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-blue-300/90">
              <Sparkles className="h-3.5 w-3.5" />
              Live security surface
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-white">
              Threat Telemetry
            </h2>
            <p className="mt-1 max-w-lg text-sm leading-relaxed text-slate-400">
              Ingestion scans, SSE event stream, and AI threat analysis.
            </p>
            {lastSynced && (
              <p className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span>
                  Synced {lastSynced}
                  {usingFallback ? ' · offline cache' : ' · live feed'}
                </span>
                {collection && (
                  <span className="inline-flex items-center gap-1">
                    <Database className="h-3 w-3" />
                    {collection.points_count ??
                      collection.vectors_count ??
                      '—'}{' '}
                    points
                  </span>
                )}
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    live
                      ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
                      : 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30'
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      live ? 'animate-pulse bg-emerald-400' : 'bg-slate-500'
                    }`}
                  />
                  {live ? 'Live stream' : 'Poll only'}
                </span>
                {streamError && (
                  <span className="text-amber-400/90">{streamError}</span>
                )}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setAutoRefresh((v) => !v)}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm font-medium text-slate-200 hover:bg-white/10"
            >
              {autoRefresh ? (
                <>
                  <Pause className="h-4 w-4" /> Auto
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" /> Paused
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                setDownloading(true);
                try {
                  exportDashboardJson({
                    stats,
                    logs,
                    health,
                    collection,
                    trend: trendData,
                  });
                } finally {
                  setDownloading(false);
                }
              }}
              disabled={downloading}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-white/10 disabled:opacity-50"
            >
              <FileJson className="h-4 w-4" />
              JSON
            </button>
            <button
              type="button"
              onClick={() => exportLogsCsv(filteredLogs)}
              disabled={!filteredLogs.length}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-white/10 disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              CSV
            </button>
            <button
              type="button"
              onClick={() => void fetchSecurityData()}
              disabled={loading}
              className="group relative inline-flex items-center gap-2 rounded-xl border border-white/10 bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-900/40 disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}
              />
              Sync
            </button>
          </div>
        </div>
      </div>

      {usingFallback && (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-100/90">
          <WifiOff className="h-4 w-4 flex-shrink-0 text-amber-300" />
          Live API unreachable — demo telemetry until Render / CORS is healthy.
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpiCards.map((m) => (
          <div key={m.label} className={`${cardBase} p-5 ring-1 ${m.ring}`}>
            <div
              className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${m.accent}`}
            />
            <div className="relative flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  {m.label}
                </p>
                {m.isStatus ? (
                  <p
                    className={`mt-2 flex items-center gap-2 text-xl font-bold ${statusColor}`}
                  >
                    <span
                      className={`h-2.5 w-2.5 animate-pulse rounded-full ${statusDot}`}
                    />
                    {m.value}
                  </p>
                ) : (
                  <p className="mt-2 text-2xl font-bold tracking-tight text-white">
                    {m.value}
                  </p>
                )}
                {m.isStatus && health && (
                  <p className="mt-1.5 text-[10px] text-slate-500">
                    Qdrant {health.qdrant_ok ? 'online' : 'offline'}
                    {health.collection_ready ? ' · collection ready' : ''}
                  </p>
                )}
              </div>
              <div
                className={`flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 ${m.iconColor}`}
              >
                <m.icon className="h-5 w-5" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* AI threat analysis */}
      <div className={`${cardBase} p-5 sm:p-6`}>
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-violet-400/20 bg-violet-500/15">
            <Sparkles className="h-4 w-4 text-violet-300" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">
              AI threat analysis
            </h3>
            <p className="text-xs text-slate-500">
              Paste email body, URL text, or document excerpt
            </p>
          </div>
        </div>
        <textarea
          value={aiText}
          onChange={(e) => setAiText(e.target.value)}
          rows={4}
          placeholder="Paste content to analyze…"
          className="w-full resize-y rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-violet-500/50 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void runAiThreatAnalysis()}
            disabled={aiLoading || !aiText.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {aiLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Analyze
          </button>
          {aiResult && (
            <span
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                aiResult.flagged
                  ? 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30'
                  : 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
              }`}
            >
              {aiResult.flagged ? 'Flagged' : 'Clean'} ·{' '}
              {aiResult.severity || '—'} · score{' '}
              {aiResult.score != null
                ? Number(aiResult.score).toFixed(2)
                : '—'}
            </span>
          )}
        </div>
        {aiResult?.rationale && (
          <p className="mt-3 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-slate-400">
            <span className="font-medium text-slate-300">
              {aiResult.detector || 'detector'}:
            </span>{' '}
            {aiResult.rationale}
          </p>
        )}
      </div>

      {/* Chart */}
      <div className={`${cardBase} p-6 sm:p-7`}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-blue-400/20 bg-blue-500/15">
              <TrendingUp className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">
                Scan &amp; threat trend
              </h3>
              <p className="text-xs text-slate-500">
                Last 7 days (demo series until API provides history)
              </p>
            </div>
          </div>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-300">
            Weekly
          </span>
        </div>
        <div className="h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={trendData}
              margin={{ top: 12, right: 12, left: -8, bottom: 0 }}
            >
              <defs>
                <linearGradient id="gradScans" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#60a5fa" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradThreats" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fbbf24" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="4 8"
                stroke="#1e293b"
                vertical={false}
              />
              <XAxis
                dataKey="day"
                stroke="#64748b"
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                stroke="#64748b"
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'rgba(15, 23, 42, 0.95)',
                  borderRadius: 14,
                  border: '1px solid rgba(148,163,184,0.2)',
                  color: '#f8fafc',
                }}
              />
              <Legend
                wrapperStyle={{ paddingTop: 12, fontSize: 12 }}
                iconType="circle"
              />
              <Area
                type="monotone"
                dataKey="scans"
                stroke="#60a5fa"
                strokeWidth={2.5}
                fill="url(#gradScans)"
                name="Scans"
              />
              <Area
                type="monotone"
                dataKey="threats"
                stroke="#fbbf24"
                strokeWidth={2.5}
                fill="url(#gradThreats)"
                name="Threats"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Event stream */}
      <div className={`${cardBase} overflow-hidden`}>
        <div className="flex flex-col items-start justify-between gap-4 border-b border-white/10 p-5 sm:p-6 lg:flex-row lg:items-center">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-400/20 bg-indigo-500/15">
              <Terminal className="h-4 w-4 text-indigo-300" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">
                Event stream
              </h3>
              <p className="text-xs text-slate-500">
                {filteredLogs.length} event
                {filteredLogs.length === 1 ? '' : 's'} shown
              </p>
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
            <div className="flex min-w-[160px] flex-1 items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-1.5">
              <Search className="h-3.5 w-3.5 text-slate-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter events…"
                className="w-full bg-transparent text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none"
              />
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-1.5">
              <Filter className="h-3.5 w-3.5 text-slate-400" />
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                className="cursor-pointer bg-transparent text-xs font-semibold text-slate-200 focus:outline-none"
              >
                <option value="ALL" className="bg-slate-900">
                  All severities
                </option>
                <option value="CRITICAL" className="bg-slate-900">
                  Critical
                </option>
                <option value="HIGH" className="bg-slate-900">
                  High
                </option>
                <option value="MEDIUM" className="bg-slate-900">
                  Medium
                </option>
                <option value="LOW" className="bg-slate-900">
                  Low
                </option>
              </select>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left">
            <thead>
              <tr className="border-b border-white/5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                <th className="px-5 py-3 sm:px-6">Event</th>
                <th className="px-5 py-3">Source</th>
                <th className="px-5 py-3">Type</th>
                <th className="px-5 py-3">Severity</th>
                <th className="px-5 py-3">Action</th>
                <th className="px-5 py-3 text-right">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-sm">
              {filteredLogs.length > 0 ? (
                filteredLogs.map((log) => (
                  <tr
                    key={log.id}
                    className="transition-colors hover:bg-white/[0.03]"
                  >
                    <td className="px-5 py-3.5 font-mono text-[11px] text-slate-500 sm:px-6">
                      {log.id}
                    </td>
                    <td className="max-w-[180px] truncate px-5 py-3.5 font-medium text-slate-200">
                      {log.filename}
                    </td>
                    <td className="px-5 py-3.5 text-slate-400">{log.type}</td>
                    <td className="px-5 py-3.5">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${severityClass(
                          log.severity
                        )}`}
                      >
                        {log.severity}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                        {log.status}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-right text-[11px] text-slate-500">
                      {log.timestamp}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td
                    colSpan={6}
                    className="py-12 text-center text-sm text-slate-500"
                  >
                    No events match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}