/**
 * MetricsCard — enterprise KPI tile for Analytics / Security / Admin.
 *
 * Features:
 *  - Accent themes, trend badges, loading skeletons
 *  - Optional sparkline (inline SVG)
 *  - Size variants (sm | md | lg)
 *  - Value formatting helpers
 *  - Clickable / keyboard-accessible
 *  - Optional footer slot and badge
 */
import React, { useId, useMemo } from 'react';
import {
  LucideIcon,
  TrendingDown,
  TrendingUp,
  Minus,
  Loader2,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MetricTrend = 'up' | 'down' | 'flat';
export type MetricAccent =
  | 'blue'
  | 'emerald'
  | 'amber'
  | 'rose'
  | 'violet'
  | 'slate'
  | 'cyan';
export type MetricSize = 'sm' | 'md' | 'lg';

export type MetricsCardProps = {
  title: string;
  value: string | number;
  /** Secondary line under the value */
  subtitle?: string;
  icon?: LucideIcon;
  /** e.g. "+12%" or "-3.2%" */
  delta?: string;
  trend?: MetricTrend;
  /** When true, invert trend colors (e.g. fewer threats = good = green down) */
  invertTrend?: boolean;
  accent?: MetricAccent;
  size?: MetricSize;
  loading?: boolean;
  /** Compact numeric sparkline (oldest → newest) */
  sparkline?: number[];
  sparklineLabel?: string;
  /** Small pill next to title */
  badge?: string;
  footer?: React.ReactNode;
  /** Format large numbers when value is numeric */
  format?: 'raw' | 'compact' | 'percent' | 'currency' | 'duration';
  currency?: string;
  onClick?: () => void;
  className?: string;
  /** Accessible description for screen readers */
  ariaLabel?: string;
};

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

const ACCENT: Record<
  MetricAccent,
  {
    ring: string;
    iconBg: string;
    iconText: string;
    glow: string;
    spark: string;
    sparkFill: string;
  }
> = {
  blue: {
    ring: 'hover:border-blue-500/40',
    iconBg: 'bg-blue-500/15 border-blue-500/25',
    iconText: 'text-blue-400',
    glow: 'shadow-blue-500/10',
    spark: 'stroke-blue-400',
    sparkFill: 'fill-blue-400/20',
  },
  emerald: {
    ring: 'hover:border-emerald-500/40',
    iconBg: 'bg-emerald-500/15 border-emerald-500/25',
    iconText: 'text-emerald-400',
    glow: 'shadow-emerald-500/10',
    spark: 'stroke-emerald-400',
    sparkFill: 'fill-emerald-400/20',
  },
  amber: {
    ring: 'hover:border-amber-500/40',
    iconBg: 'bg-amber-500/15 border-amber-500/25',
    iconText: 'text-amber-400',
    glow: 'shadow-amber-500/10',
    spark: 'stroke-amber-400',
    sparkFill: 'fill-amber-400/20',
  },
  rose: {
    ring: 'hover:border-rose-500/40',
    iconBg: 'bg-rose-500/15 border-rose-500/25',
    iconText: 'text-rose-400',
    glow: 'shadow-rose-500/10',
    spark: 'stroke-rose-400',
    sparkFill: 'fill-rose-400/20',
  },
  violet: {
    ring: 'hover:border-violet-500/40',
    iconBg: 'bg-violet-500/15 border-violet-500/25',
    iconText: 'text-violet-400',
    glow: 'shadow-violet-500/10',
    spark: 'stroke-violet-400',
    sparkFill: 'fill-violet-400/20',
  },
  slate: {
    ring: 'hover:border-slate-500/40',
    iconBg: 'bg-slate-500/15 border-slate-500/25',
    iconText: 'text-slate-300',
    glow: 'shadow-slate-500/10',
    spark: 'stroke-slate-400',
    sparkFill: 'fill-slate-400/20',
  },
  cyan: {
    ring: 'hover:border-cyan-500/40',
    iconBg: 'bg-cyan-500/15 border-cyan-500/25',
    iconText: 'text-cyan-400',
    glow: 'shadow-cyan-500/10',
    spark: 'stroke-cyan-400',
    sparkFill: 'fill-cyan-400/20',
  },
};

const SIZE = {
  sm: {
    pad: 'p-3.5',
    title: 'text-[10px]',
    value: 'text-xl',
    iconBox: 'h-9 w-9',
    icon: 'h-4 w-4',
  },
  md: {
    pad: 'p-5',
    title: 'text-[11px]',
    value: 'text-2xl',
    iconBox: 'h-11 w-11',
    icon: 'h-5 w-5',
  },
  lg: {
    pad: 'p-6',
    title: 'text-xs',
    value: 'text-3xl',
    iconBox: 'h-12 w-12',
    icon: 'h-6 w-6',
  },
} as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatMetricValue(
  value: string | number,
  format: NonNullable<MetricsCardProps['format']> = 'raw',
  currency = 'USD',
): string {
  if (typeof value === 'string') return value;

  if (format === 'raw') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  if (format === 'compact') {
    return new Intl.NumberFormat(undefined, {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(value);
  }

  if (format === 'percent') {
    const n = Math.abs(value) <= 1 ? value * 100 : value;
    return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  }

  if (format === 'currency') {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  }

  if (format === 'duration') {
    // value in milliseconds
    if (value < 1000) return `${Math.round(value)}ms`;
    if (value < 60_000) return `${(value / 1000).toFixed(1)}s`;
    const m = Math.floor(value / 60_000);
    const s = Math.round((value % 60_000) / 1000);
    return `${m}m ${s}s`;
  }

  return String(value);
}

function buildSparkPath(
  values: number[],
  width: number,
  height: number,
  pad = 2,
): { line: string; area: string } {
  if (!values.length) return { line: '', area: '' };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = width - pad * 2;
  const h = height - pad * 2;

  const pts = values.map((v, i) => {
    const x = pad + (values.length === 1 ? w / 2 : (i / (values.length - 1)) * w);
    const y = pad + h - ((v - min) / span) * h;
    return [x, y] as const;
  });

  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ');
  const area = `${line} L${pts[pts.length - 1][0]},${height - pad} L${pts[0][0]},${height - pad} Z`;
  return { line, area };
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function TrendBadge({
  trend,
  delta,
  invertTrend,
}: {
  trend?: MetricTrend;
  delta?: string;
  invertTrend?: boolean;
}) {
  if (!delta && !trend) return null;

  let t: MetricTrend = trend ?? 'flat';
  if (invertTrend && t === 'up') t = 'down';
  else if (invertTrend && t === 'down') t = 'up';

  const color =
    t === 'up'
      ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
      : t === 'down'
        ? 'text-rose-400 bg-rose-500/10 border-rose-500/20'
        : 'text-slate-400 bg-slate-500/10 border-slate-500/20';

  const Icon = t === 'up' ? TrendingUp : t === 'down' ? TrendingDown : Minus;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium border ${color}`}
    >
      <Icon className="w-3 h-3 shrink-0" />
      {delta ?? t}
    </span>
  );
}

function Sparkline({
  values,
  accent,
  label,
}: {
  values: number[];
  accent: MetricAccent;
  label?: string;
}) {
  const id = useId();
  const width = 96;
  const height = 36;
  const { line, area } = useMemo(
    () => buildSparkPath(values, width, height),
    [values],
  );
  const a = ACCENT[accent];

  if (values.length < 2) return null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="shrink-0 opacity-90"
      aria-hidden={!label}
      role={label ? 'img' : undefined}
      aria-label={label}
    >
      <defs>
        <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} className={a.sparkFill} style={{ color: undefined }} />
      <path
        d={line}
        fill="none"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={a.spark}
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MetricsCard({
  title,
  value,
  subtitle,
  icon: Icon,
  delta,
  trend,
  invertTrend = false,
  accent = 'blue',
  size = 'md',
  loading = false,
  sparkline,
  sparklineLabel,
  badge,
  footer,
  format = 'raw',
  currency = 'USD',
  onClick,
  className = '',
  ariaLabel,
}: MetricsCardProps) {
  const a = ACCENT[accent];
  const s = SIZE[size];
  const interactive = Boolean(onClick);
  const display = loading
    ? null
    : formatMetricValue(value, format, currency);

  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={ariaLabel ?? title}
      onClick={onClick}
      onKeyDown={(e) => {
        if (!interactive) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={[
        'relative rounded-2xl border border-white/10 bg-slate-900/80 backdrop-blur-sm',
        'shadow-lg transition-all duration-200',
        s.pad,
        a.ring,
        a.glow,
        interactive ? 'cursor-pointer hover:bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50' : '',
        className,
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p
              className={`${s.title} font-semibold uppercase tracking-wider text-slate-400`}
            >
              {title}
            </p>
            {badge ? (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-slate-400">
                {badge}
              </span>
            ) : null}
          </div>

          {loading ? (
            <div className="mt-3 flex items-center gap-2">
              <div className="h-8 w-24 animate-pulse rounded-lg bg-slate-700/60" />
              <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
            </div>
          ) : (
            <p
              className={`mt-2 ${s.value} font-semibold tracking-tight text-slate-50 truncate`}
            >
              {display}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TrendBadge
              trend={trend}
              delta={delta}
              invertTrend={invertTrend}
            />
            {subtitle ? (
              <span className="text-xs text-slate-500 truncate">{subtitle}</span>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          {Icon ? (
            <div
              className={[
                'flex shrink-0 items-center justify-center rounded-xl border',
                s.iconBox,
                a.iconBg,
                a.iconText,
              ].join(' ')}
            >
              <Icon className={s.icon} />
            </div>
          ) : null}

          {sparkline && sparkline.length >= 2 && !loading ? (
            <Sparkline
              values={sparkline}
              accent={accent}
              label={sparklineLabel}
            />
          ) : null}
        </div>
      </div>

      {footer ? (
        <div className="mt-4 pt-3 border-t border-white/5 text-xs text-slate-500">
          {footer}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Convenience grid wrapper (optional export)
// ---------------------------------------------------------------------------

export function MetricsCardGrid({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={[
        'grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  );
}