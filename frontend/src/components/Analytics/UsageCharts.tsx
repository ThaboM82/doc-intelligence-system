/**
 * UsageCharts — request / token / cost / latency charts for Analytics.
 * Pure SVG (no chart library). Matches MetricsCard styling.
 */
import React, { useId, useMemo, useState } from 'react';
import { Activity, Coins, Timer, Zap } from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type UsagePoint = {
  /** Label on X axis (e.g. "Mon", "10:00", "2026-03-20") */
  label: string;
  requests?: number;
  tokens?: number;
  costUsd?: number;
  latencyMs?: number;
};

export type UsageMetricKey = 'requests' | 'tokens' | 'costUsd' | 'latencyMs';

export type UsageChartsProps = {
  data: UsagePoint[];
  /** Which series to show (default: all present in data) */
  metrics?: UsageMetricKey[];
  title?: string;
  subtitle?: string;
  loading?: boolean;
  height?: number;
  className?: string;
  /** Controlled active metric; uncontrolled if omitted */
  activeMetric?: UsageMetricKey;
  onMetricChange?: (key: UsageMetricKey) => void;
};

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const METRIC_META: Record<
  UsageMetricKey,
  {
    label: string;
    color: string;
    stroke: string;
    fill: string;
    icon: typeof Activity;
    format: (n: number) => string;
  }
> = {
  requests: {
    label: 'Requests',
    color: 'text-blue-400',
    stroke: '#60a5fa',
    fill: 'rgba(96, 165, 250, 0.18)',
    icon: Activity,
    format: (n) =>
      n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(Math.round(n)),
  },
  tokens: {
    label: 'Tokens',
    color: 'text-violet-400',
    stroke: '#a78bfa',
    fill: 'rgba(167, 139, 250, 0.18)',
    icon: Zap,
    format: (n) =>
      n >= 1_000_000
        ? `${(n / 1_000_000).toFixed(2)}M`
        : n >= 1000
          ? `${(n / 1000).toFixed(1)}k`
          : String(Math.round(n)),
  },
  costUsd: {
    label: 'Cost (USD)',
    color: 'text-amber-400',
    stroke: '#fbbf24',
    fill: 'rgba(251, 191, 36, 0.18)',
    icon: Coins,
    format: (n) =>
      `$${n.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      })}`,
  },
  latencyMs: {
    label: 'Latency',
    color: 'text-cyan-400',
    stroke: '#22d3ee',
    fill: 'rgba(34, 211, 238, 0.18)',
    icon: Timer,
    format: (n) => (n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`),
  },
};

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

function seriesValues(data: UsagePoint[], key: UsageMetricKey): number[] {
  return data.map((d) => {
    const v = d[key];
    return typeof v === 'number' && Number.isFinite(v) ? v : 0;
  });
}

function buildPaths(
  values: number[],
  width: number,
  height: number,
  padX = 8,
  padY = 12,
): { line: string; area: string; points: { x: number; y: number; v: number }[] } {
  if (!values.length) return { line: '', area: '', points: [] };

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const points = values.map((v, i) => {
    const x =
      padX + (values.length === 1 ? w / 2 : (i / (values.length - 1)) * w);
    const y = padY + h - ((v - min) / span) * h;
    return { x, y, v };
  });

  const line = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');
  const area = `${line} L${points[points.length - 1].x.toFixed(2)},${(height - padY).toFixed(2)} L${points[0].x.toFixed(2)},${(height - padY).toFixed(2)} Z`;

  return { line, area, points };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UsageCharts({
  data,
  metrics,
  title = 'Usage',
  subtitle = 'API activity over time',
  loading = false,
  height = 220,
  className = '',
  activeMetric: controlledMetric,
  onMetricChange,
}: UsageChartsProps) {
  const gradId = useId();

  const available = useMemo(() => {
    const keys: UsageMetricKey[] = metrics?.length
      ? metrics
      : (['requests', 'tokens', 'costUsd', 'latencyMs'] as UsageMetricKey[]).filter(
          (k) => data.some((d) => typeof d[k] === 'number'),
        );
    return keys.length ? keys : (['requests'] as UsageMetricKey[]);
  }, [data, metrics]);

  const [internalMetric, setInternalMetric] = useState<UsageMetricKey>(
    available[0] ?? 'requests',
  );

  const active =
    controlledMetric && available.includes(controlledMetric)
      ? controlledMetric
      : available.includes(internalMetric)
        ? internalMetric
        : available[0];

  const setActive = (k: UsageMetricKey) => {
    setInternalMetric(k);
    onMetricChange?.(k);
  };

  const values = useMemo(() => seriesValues(data, active), [data, active]);
  const meta = METRIC_META[active];
  const Icon = meta.icon;

  const chartW = 640;
  const chartH = height;
  const { line, area, points } = useMemo(
    () => buildPaths(values, chartW, chartH),
    [values, chartW, chartH],
  );

  const total = values.reduce((a, b) => a + b, 0);
  const peak = values.length ? Math.max(...values) : 0;
  const avg = values.length ? total / values.length : 0;

  const [hover, setHover] = useState<number | null>(null);

  return (
    <div
      className={[
        'rounded-2xl border border-white/10 bg-slate-900/80 backdrop-blur-sm shadow-lg',
        'p-5',
        className,
      ].join(' ')}
    >
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5">
              <Icon className={`h-4 w-4 ${meta.color}`} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
              <p className="text-xs text-slate-500">{subtitle}</p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {available.map((k) => {
            const m = METRIC_META[k];
            const on = k === active;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setActive(k)}
                className={[
                  'px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors',
                  on
                    ? 'bg-white/10 border-white/20 text-slate-100'
                    : 'bg-transparent border-white/5 text-slate-500 hover:text-slate-300 hover:border-white/10',
                ].join(' ')}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Stats row */}
      <div className="mb-4 grid grid-cols-3 gap-3">
        {[
          { label: 'Total', value: meta.format(total) },
          { label: 'Average', value: meta.format(avg) },
          { label: 'Peak', value: meta.format(peak) },
        ].map((s) => (
          <div
            key={s.label}
            className="rounded-xl border border-white/5 bg-white/[0.03] px-3 py-2"
          >
            <p className="text-[10px] uppercase tracking-wider text-slate-500">
              {s.label}
            </p>
            <p className={`text-sm font-semibold ${meta.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="relative w-full overflow-hidden rounded-xl border border-white/5 bg-slate-950/50">
        {loading ? (
          <div
            className="flex items-center justify-center text-slate-500 text-sm"
            style={{ height }}
          >
            Loading usage…
          </div>
        ) : !data.length ? (
          <div
            className="flex items-center justify-center text-slate-500 text-sm"
            style={{ height }}
          >
            No usage data yet
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${chartW} ${chartH}`}
            className="w-full h-auto"
            style={{ height }}
            preserveAspectRatio="none"
            onMouseLeave={() => setHover(null)}
          >
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={meta.stroke} stopOpacity="0.35" />
                <stop offset="100%" stopColor={meta.stroke} stopOpacity="0" />
              </linearGradient>
            </defs>

            {/* Grid lines */}
            {[0.25, 0.5, 0.75].map((t) => (
              <line
                key={t}
                x1={8}
                x2={chartW - 8}
                y1={12 + (chartH - 24) * t}
                y2={12 + (chartH - 24) * t}
                stroke="rgba(148,163,184,0.12)"
                strokeDasharray="4 4"
              />
            ))}

            <path d={area} fill={`url(#${gradId})`} />
            <path
              d={line}
              fill="none"
              stroke={meta.stroke}
              strokeWidth="2.25"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />

            {/* Hover targets */}
            {points.map((p, i) => (
              <g key={i}>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={hover === i ? 4.5 : 0}
                  fill={meta.stroke}
                  className="transition-all"
                />
                <rect
                  x={p.x - chartW / points.length / 2}
                  y={0}
                  width={Math.max(8, chartW / points.length)}
                  height={chartH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            ))}
          </svg>
        )}

        {/* Tooltip */}
        {hover != null && data[hover] && !loading ? (
          <div className="pointer-events-none absolute top-3 right-3 rounded-lg border border-white/10 bg-slate-900/95 px-3 py-2 text-xs shadow-xl">
            <p className="text-slate-400 mb-0.5">{data[hover].label}</p>
            <p className={`font-semibold ${meta.color}`}>
              {meta.format(values[hover] ?? 0)}
            </p>
          </div>
        ) : null}
      </div>

      {/* X labels */}
      {data.length > 0 && !loading ? (
        <div className="mt-2 flex justify-between gap-1 px-1">
          {data.map((d, i) => {
            // Show first, last, and a few middle labels to avoid clutter
            const show =
              data.length <= 8 ||
              i === 0 ||
              i === data.length - 1 ||
              i === Math.floor(data.length / 2);
            return (
              <span
                key={`${d.label}-${i}`}
                className="text-[10px] text-slate-600 truncate text-center flex-1"
              >
                {show ? d.label : ''}
              </span>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Demo / empty helpers
// ---------------------------------------------------------------------------

/** Build sample points for local UI development */
export function buildSampleUsage(days = 14): UsagePoint[] {
  const out: UsagePoint[] = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const label = d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    });
    const requests = Math.round(80 + Math.random() * 140 + (days - i) * 3);
    const tokens = requests * Math.round(400 + Math.random() * 800);
    out.push({
      label,
      requests,
      tokens,
      costUsd: tokens * 0.00002 + Math.random() * 0.05,
      latencyMs: 200 + Math.random() * 600,
    });
  }
  return out;
}