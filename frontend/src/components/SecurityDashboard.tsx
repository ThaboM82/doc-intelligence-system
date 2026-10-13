import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
} from '../lib/apiClient';

interface SecurityStats {
  totalScanned: number;
  threatsDetected: number;
  policyViolations: number;
  systemStatus: string;
  criticalCount: number;
}

interface SecurityLog {
  id: string;
  timestamp: string;
  filename: string;
  type: string;
  severity: string;
  status: string;
}

interface CollectionStats {
  status?: string;
  points_count?: number;
  vectors_count?: number;
  indexed_vectors_count?: number;
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

function mapTelemetryToLogs(events: TelemetryEvent[]): SecurityLog[] {
  return events.map((ev, i) => {
    const sev = String(ev.severity || 'low');
    return {
      id: `TEL-${String(i + 1).padStart(4, '0')}`,
      timestamp: ev.timestamp,
      filename: ev.source_ip || '—',
      type: ev.threat_type,
      severity: sev.charAt(0).toUpperCase() + sev.slice(1).toLowerCase(),
      status:
        sev.toLowerCase() === 'critical' || sev.toLowerCase() === 'high'
          ? 'Blocked'
          : 'Logged',
    };
  });
}

function severityClass(severity: string) {
  const s = severity.toLowerCase();
  if (s === 'high' || s === 'critical') {
    return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30';
  }
  if (s === 'medium') {
    return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
  }
  return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30';
}

function exportLogsCsv(logs: SecurityLog[]) {
  const header = ['id', 'timestamp', 'source', 'type', 'severity', 'status'];
  const rows = logs.map((l) =>
    [l.id, l.timestamp, l.filename, l.type, l.severity, l.status]
      .map((c) => `"${String(c).replace(/"/g, '""')}"`)
      .join(',')
  );
  const blob = new Blob([[header.join(','), ...rows].join('\n')], {
    type: 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `security-events-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
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

  const fetchSecurityData = useCallback(async () => {
    setLoading(true);
    try {
      const [healthRes, telemRes, collRes] = await Promise.allSettled([
        apiClient.getHealth(),
        apiClient.getTelemetrySummary(),
        typeof apiClient.getCollectionStats === 'function'
          ? apiClient.getCollectionStats()
          : Promise.reject(new Error('no collection stats')),
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
          totalScanned: t.total_caught || prev.totalScanned,
          threatsDetected: t.active_threats ?? prev.threatsDetected,
          policyViolations: Math.max(
            prev.policyViolations,
            Math.floor((t.active_threats || 0) / 2)
          ),
          criticalCount: critical,
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
    const id = window.setInterval(() => void fetchSecurityData(), 60_000);
    return () => window.clearInterval(id);
  }, [fetchSecurityData]);

  const filteredLogs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.filter((log) => {
      if (filterSeverity !== 'ALL' && log.severity.toUpperCase() !== filterSeverity) {
        return false;
      }
      if (!q) return true;
      return (
        log.filename.toLowerCase().includes(q) ||
        log.type.toLowerCase().includes(q) ||
        log.id.toLowerCase().includes(q) ||
        log.status.toLowerCase().includes(q)
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
    <div className="space-y-6 max-w-5xl mx-auto text-slate-100">
      {/* Hero */}
      <div className={`${cardBase} p-6 sm:p-8`}>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_rgba(59,130,246,0.15),_transparent_50%)] pointer-events-none" />
        <div className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-blue-300/90 mb-2">
              <Sparkles className="w-3.5 h-3.5" />
              Live security surface
            </div>
            <h2 className="text-2xl font-bold text-white tracking-tight">Threat Telemetry</h2>
            <p className="text-sm text-slate-400 mt-1 max-w-lg leading-relaxed">
              Ingestion scans, policy engines, and vector-store health in one view.
            </p>
            {lastSynced && (
              <p className="text-[11px] text-slate-500 mt-2">
                Synced {lastSynced}
                {usingFallback ? ' · offline cache' : ' · live feed'}
                {collection && (
                  <span className="ml-2 inline-flex items-center gap-1">
                    <Database className="w-3 h-3" />
                    {collection.points_count ?? collection.vectors_count ?? '—'} points
                  </span>
                )}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => exportLogsCsv(filteredLogs)}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-slate-200 bg-white/5 border border-white/10 hover:bg-white/10"
            >
              <Download className="w-4 h-4" />
              Export CSV
            </button>
            <button
              type="button"
              onClick={() => void fetchSecurityData()}
              disabled={loading}
              className="group relative inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-lg shadow-blue-900/40 border border-white/10 disabled:opacity-50 transition-all"
            >
              <RefreshCw
                className={`w-4 h-4 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`}
              />
              Sync
            </button>
          </div>
        </div>
      </div>

      {usingFallback && (
        <div className="flex items-center gap-3 text-sm text-amber-100/90 bg-amber-500/10 border border-amber-500/25 rounded-2xl px-4 py-3 backdrop-blur">
          <WifiOff className="w-4 h-4 flex-shrink-0 text-amber-300" />
          <span>
            Live API unreachable — showing demo telemetry. Check Render health / CORS.
          </span>
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map((m) => (
          <div key={m.label} className={`${cardBase} p-5 ring-1 ${m.ring}`}>
            <div className={`absolute inset-0 bg-gradient-to-br ${m.accent} pointer-events-none`} />
            <div className="relative flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  {m.label}
                </p>
                {m.isStatus ? (
                  <p className={`mt-2 text-xl font-bold flex items-center gap-2 ${statusColor}`}>
                    <span className={`w-2.5 h-2.5 rounded-full animate-pulse ${statusDot}`} />
                    {m.value}
                  </p>
                ) : (
                  <p className="mt-2 text-2xl font-bold text-white tracking-tight">{m.value}</p>
                )}
                {m.isStatus && health && (
                  <p className="text-[10px] text-slate-500 mt-1.5">
                    Qdrant {health.qdrant_ok ? 'online' : 'offline'}
                    {health.collection_ready ? ' · collection ready' : ''}
                  </p>
                )}
              </div>
              <div
                className={`w-11 h-11 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center ${m.iconColor}`}
              >
                <m.icon className="w-5 h-5" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className={`${cardBase} p-6 sm:p-7`}>
        <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl bg-blue-500/15 border border-blue-400/20 flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-blue-400" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Scan &amp; threat trend</h3>
              <p className="text-xs text-slate-500">Last 7 days (demo series until API provides history)</p>
            </div>
          </div>
          <span className="text-[11px] font-medium px-3 py-1 rounded-full bg-white/5 border border-white/10 text-slate-300">
            Weekly
          </span>
        </div>

        <div className="h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trendData} margin={{ top: 12, right: 12, left: -8, bottom: 0 }}>
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
              <CartesianGrid strokeDasharray="4 8" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="day" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ stroke: '#334155', strokeDasharray: '4 4' }}
                contentStyle={{
                  backgroundColor: 'rgba(15, 23, 42, 0.95)',
                  borderRadius: 14,
                  border: '1px solid rgba(148,163,184,0.2)',
                  color: '#f8fafc',
                  boxShadow: '0 20px 40px rgba(0,0,0,0.45)',
                }}
              />
              <Legend wrapperStyle={{ paddingTop: 12, fontSize: 12 }} iconType="circle" />
              <Area
                type="monotone"
                dataKey="scans"
                stroke="#60a5fa"
                strokeWidth={2.5}
                fill="url(#gradScans)"
                name="Scans"
                activeDot={{ r: 5, strokeWidth: 0 }}
              />
              <Area
                type="monotone"
                dataKey="threats"
                stroke="#fbbf24"
                strokeWidth={2.5}
                fill="url(#gradThreats)"
                name="Threats"
                activeDot={{ r: 5, strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Event stream */}
      <div className={`${cardBase} overflow-hidden`}>
        <div className="p-5 sm:p-6 border-b border-white/10 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-500/15 border border-indigo-400/20 flex items-center justify-center">
              <Terminal className="w-4 h-4 text-indigo-300" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Event stream</h3>
              <p className="text-xs text-slate-500">
                {filteredLogs.length} event{filteredLogs.length === 1 ? '' : 's'} shown
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto">
            <div className="flex items-center gap-2 bg-black/30 rounded-xl px-3 py-1.5 border border-white/10 flex-1 min-w-[160px]">
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter events…"
                className="bg-transparent text-xs text-slate-200 focus:outline-none w-full placeholder:text-slate-500"
              />
            </div>
            <div className="flex items-center gap-2 bg-black/30 rounded-xl px-3 py-1.5 border border-white/10">
              <Filter className="w-3.5 h-3.5 text-slate-400" />
              <select
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                className="bg-transparent text-xs font-semibold text-slate-200 focus:outline-none cursor-pointer"
              >
                <option value="ALL" className="bg-slate-900">
                  All severities
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
                <option value="CRITICAL" className="bg-slate-900">
                  Critical
                </option>
              </select>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[640px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-[0.12em] text-slate-500 font-semibold border-b border-white/5">
                <th className="py-3 px-5 sm:px-6">Event</th>
                <th className="py-3 px-5">Source</th>
                <th className="py-3 px-5">Type</th>
                <th className="py-3 px-5">Severity</th>
                <th className="py-3 px-5">Action</th>
                <th className="py-3 px-5 text-right">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-sm">
              {filteredLogs.length > 0 ? (
                filteredLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-white/[0.03] transition-colors">
                    <td className="py-3.5 px-5 sm:px-6 font-mono text-[11px] text-slate-500">
                      {log.id}
                    </td>
                    <td className="py-3.5 px-5 font-medium text-slate-200 max-w-[180px] truncate">
                      {log.filename}
                    </td>
                    <td className="py-3.5 px-5 text-slate-400">{log.type}</td>
                    <td className="py-3.5 px-5">
                      <span
                        className={`inline-flex px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${severityClass(
                          log.severity
                        )}`}
                      >
                        {log.severity}
                      </span>
                    </td>
                    <td className="py-3.5 px-5">
                      <span className="text-[11px] font-medium text-slate-300 bg-white/5 border border-white/10 px-2.5 py-1 rounded-lg">
                        {log.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-5 text-right text-[11px] text-slate-500">
                      {log.timestamp}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500 text-sm">
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