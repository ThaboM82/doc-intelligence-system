import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  LayoutDashboard,
  RefreshCw,
  ShieldAlert,
  Activity,
  Database,
  Cpu,
  AlertTriangle,
  ScanSearch,
  Loader2,
  WifiOff,
  Terminal,
} from 'lucide-react';
import apiClient from '../lib/apiClient';

type DashboardPayload = {
  generated_at?: string;
  uptime_seconds?: number;
  http?: {
    total_requests?: number;
    successful_requests?: number;
    failed_requests?: number;
    average_latency_ms?: number;
    endpoint_distribution?: Record<string, number>;
  };
  threats?: {
    total_caught?: number;
    active_threats?: number;
    severity_counts?: Record<string, number>;
    ai_scans_total?: number;
    ai_flagged_total?: number;
  };
  product?: {
    scans_total?: number;
    quarantine_total?: number;
    ingest_success?: number;
    ingest_failed?: number;
    rag_queries?: number;
  };
  recent_events?: Array<{
    timestamp?: string;
    threat_type?: string;
    source_ip?: string;
    severity?: string;
    confidence_score?: number;
    detector?: string;
    detail?: string;
  }>;
};

type ScanResult = {
  flagged: boolean;
  score: number;
  severity: string;
  detector: string;
  hits?: Array<{ type?: string; weight?: number }>;
  rationale?: string | null;
  ai_label?: string | null;
};

function formatUptime(sec?: number) {
  if (sec == null || Number.isNaN(sec)) return '—';
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function severityPill(sev?: string) {
  const s = (sev || '').toLowerCase();
  if (s === 'critical' || s === 'high')
    return 'bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30';
  if (s === 'medium') return 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30';
  return 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30';
}

const card =
  'rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/80 to-slate-950/90 shadow-lg backdrop-blur-xl';

export default function AdminDashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scanText, setScanText] = useState('');
  const [useAi, setUseAi] = useState(true);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let payload: DashboardPayload;
      if (typeof (apiClient as any).getAdminDashboard === 'function') {
        payload = await (apiClient as any).getAdminDashboard();
      } else {
        payload = await apiClient.get('/api/v1/admin/dashboard');
      }
      setData(payload);
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Failed to load admin dashboard (need admin token / TELEMETRY_READ).';
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  const topEndpoints = useMemo(() => {
    const dist = data?.http?.endpoint_distribution || {};
    return Object.entries(dist)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);
  }, [data]);

  const runThreatScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scanText.trim() || scanLoading) return;
    setScanLoading(true);
    setScanResult(null);
    try {
      const result = await apiClient.post<ScanResult>('/api/v1/admin/threat-scan', {
        text: scanText.trim(),
        use_ai: useAi,
      });
      setScanResult(result);
      void load();
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Threat scan failed';
      setScanResult({
        flagged: false,
        score: 0,
        severity: 'low',
        detector: 'error',
        rationale: msg,
      });
    } finally {
      setScanLoading(false);
    }
  };

  const threats = data?.threats;
  const product = data?.product;
  const http = data?.http;
  const events = data?.recent_events || [];

  return (
    <div className="space-y-6 max-w-6xl mx-auto text-slate-100">
      {/* Header */}
      <div className={`${card} p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4`}>
        <div>
          <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-indigo-300 mb-2">
            <LayoutDashboard className="w-3.5 h-3.5" />
            Admin control plane
          </div>
          <h2 className="text-2xl font-bold text-white">Operations dashboard</h2>
          <p className="text-sm text-slate-400 mt-1">
            HTTP metrics, AI threat detection, ingest &amp; RAG volume.
          </p>
          {data?.generated_at && (
            <p className="text-[11px] text-slate-500 mt-2">
              Snapshot {data.generated_at} · uptime {formatUptime(data.uptime_seconds)}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 border border-white/10 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-amber-100 bg-amber-500/10 border border-amber-500/25 rounded-2xl px-4 py-3">
          <WifiOff className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: 'Requests',
            value: http?.total_requests ?? '—',
            sub: `${http?.average_latency_ms ?? '—'} ms avg`,
            icon: Activity,
            color: 'text-blue-400',
          },
          {
            label: 'Threats caught',
            value: threats?.total_caught ?? '—',
            sub: `${threats?.active_threats ?? 0} active`,
            icon: ShieldAlert,
            color: 'text-amber-400',
          },
          {
            label: 'AI flagged',
            value: threats?.ai_flagged_total ?? '—',
            sub: `${threats?.ai_scans_total ?? 0} AI scans`,
            icon: Cpu,
            color: 'text-violet-400',
          },
          {
            label: 'RAG queries',
            value: product?.rag_queries ?? '—',
            sub: `ingest ok ${product?.ingest_success ?? 0} / fail ${product?.ingest_failed ?? 0}`,
            icon: Database,
            color: 'text-emerald-400',
          },
        ].map((k) => (
          <div key={k.label} className={`${card} p-5`}>
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
                  {k.label}
                </p>
                <p className="text-2xl font-bold text-white mt-1">{k.value}</p>
                <p className="text-[11px] text-slate-500 mt-1">{k.sub}</p>
              </div>
              <k.icon className={`w-5 h-5 ${k.color}`} />
            </div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Endpoints */}
        <div className={`${card} p-6`}>
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
            <Terminal className="w-4 h-4 text-slate-400" />
            Top endpoints
          </h3>
          {topEndpoints.length === 0 ? (
            <p className="text-sm text-slate-500">No traffic yet.</p>
          ) : (
            <ul className="space-y-2">
              {topEndpoints.map(([path, count]) => (
                <li
                  key={path}
                  className="flex items-center justify-between text-sm gap-3 border-b border-white/5 pb-2"
                >
                  <code className="text-xs text-slate-300 truncate">{path}</code>
                  <span className="text-slate-400 font-mono text-xs">{count}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-white/5 rounded-lg p-2">
              <p className="text-slate-500">Success</p>
              <p className="text-emerald-400 font-semibold">{http?.successful_requests ?? 0}</p>
            </div>
            <div className="bg-white/5 rounded-lg p-2">
              <p className="text-slate-500">Failed</p>
              <p className="text-rose-400 font-semibold">{http?.failed_requests ?? 0}</p>
            </div>
            <div className="bg-white/5 rounded-lg p-2">
              <p className="text-slate-500">Quarantine</p>
              <p className="text-amber-400 font-semibold">{product?.quarantine_total ?? 0}</p>
            </div>
          </div>
        </div>

        {/* AI threat scan */}
        <div className={`${card} p-6 space-y-4`}>
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <ScanSearch className="w-4 h-4 text-violet-400" />
            AI threat scan
          </h3>
          <p className="text-xs text-slate-500">
            Heuristic + optional LLM classifier. Requires analyst/admin token.
          </p>
          <form onSubmit={(e) => void runThreatScan(e)} className="space-y-3">
            <textarea
              value={scanText}
              onChange={(e) => setScanText(e.target.value)}
              rows={4}
              placeholder="Paste prompt, email body, or document excerpt…"
              className="w-full px-3 py-2 rounded-xl bg-black/30 border border-white/10 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={useAi}
                onChange={(e) => setUseAi(e.target.checked)}
                className="rounded border-slate-600"
              />
              Use AI (OpenAI) hybrid scoring
            </label>
            <button
              type="submit"
              disabled={scanLoading || !scanText.trim()}
              className="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold disabled:opacity-50 inline-flex items-center justify-center gap-2"
            >
              {scanLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Scanning…
                </>
              ) : (
                'Run analysis'
              )}
            </button>
          </form>
          {scanResult && (
            <div className="rounded-xl border border-white/10 bg-black/20 p-4 space-y-2 text-sm">
              <div className="flex flex-wrap gap-2 items-center">
                <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${severityPill(scanResult.severity)}`}>
                  {scanResult.severity}
                </span>
                <span className="text-slate-400 text-xs">
                  score {(scanResult.score * 100).toFixed(0)}% · {scanResult.detector}
                  {scanResult.flagged ? ' · FLAGGED' : ' · clean'}
                </span>
              </div>
              {scanResult.rationale && (
                <p className="text-slate-300 text-xs leading-relaxed">{scanResult.rationale}</p>
              )}
              {scanResult.hits && scanResult.hits.length > 0 && (
                <p className="text-[11px] text-slate-500">
                  Hits: {scanResult.hits.map((h) => h.type).filter(Boolean).join(', ')}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Events */}
      <div className={`${card} overflow-hidden`}>
        <div className="p-5 border-b border-white/10 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-white">Recent threat events</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm min-w-[640px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-white/5">
                <th className="py-3 px-5">When</th>
                <th className="py-3 px-5">Type</th>
                <th className="py-3 px-5">Source</th>
                <th className="py-3 px-5">Severity</th>
                <th className="py-3 px-5">Detector</th>
                <th className="py-3 px-5">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {events.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-slate-500">
                    {loading ? 'Loading…' : 'No events recorded yet.'}
                  </td>
                </tr>
              ) : (
                events.map((ev, i) => (
                  <tr key={`${ev.timestamp}-${i}`} className="hover:bg-white/[0.03]">
                    <td className="py-3 px-5 font-mono text-[11px] text-slate-500">
                      {ev.timestamp}
                    </td>
                    <td className="py-3 px-5 text-slate-200">{ev.threat_type}</td>
                    <td className="py-3 px-5 font-mono text-xs text-slate-400">
                      {ev.source_ip}
                    </td>
                    <td className="py-3 px-5">
                      <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${severityPill(ev.severity)}`}>
                        {ev.severity}
                      </span>
                    </td>
                    <td className="py-3 px-5 text-xs text-slate-400">{ev.detector || '—'}</td>
                    <td className="py-3 px-5 text-slate-400">
                      {((ev.confidence_score || 0) * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}