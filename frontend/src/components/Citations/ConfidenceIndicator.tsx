/**
 * ConfidenceIndicator — visual confidence for RAG answers / citations.
 */
import React from 'react';
import { ShieldCheck, ShieldAlert, ShieldQuestion } from 'lucide-react';

export type ConfidenceLevel = 'high' | 'medium' | 'low' | 'unknown';

export type ConfidenceIndicatorProps = {
  /** 0–1 or 0–100 */
  score?: number | null;
  level?: ConfidenceLevel;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  showBar?: boolean;
  className?: string;
};

function normalizeScore(score?: number | null): number | null {
  if (score == null || Number.isNaN(score)) return null;
  if (score < 0) return 0;
  if (score <= 1) return score;
  if (score <= 100) return score / 100;
  return 1;
}

export function scoreToLevel(score?: number | null): ConfidenceLevel {
  const n = normalizeScore(score);
  if (n == null) return 'unknown';
  if (n >= 0.75) return 'high';
  if (n >= 0.45) return 'medium';
  return 'low';
}

const LEVEL_META: Record<
  ConfidenceLevel,
  {
    label: string;
    bar: string;
    text: string;
    bg: string;
    icon: typeof ShieldCheck;
  }
> = {
  high: {
    label: 'High confidence',
    bar: 'bg-emerald-400',
    text: 'text-emerald-400',
    bg: 'bg-emerald-500/10 border-emerald-500/20',
    icon: ShieldCheck,
  },
  medium: {
    label: 'Medium confidence',
    bar: 'bg-amber-400',
    text: 'text-amber-400',
    bg: 'bg-amber-500/10 border-amber-500/20',
    icon: ShieldQuestion,
  },
  low: {
    label: 'Low confidence',
    bar: 'bg-rose-400',
    text: 'text-rose-400',
    bg: 'bg-rose-500/10 border-rose-500/20',
    icon: ShieldAlert,
  },
  unknown: {
    label: 'Unknown',
    bar: 'bg-slate-500',
    text: 'text-slate-400',
    bg: 'bg-slate-500/10 border-slate-500/20',
    icon: ShieldQuestion,
  },
};

const SIZE = {
  sm: { icon: 'h-3.5 w-3.5', text: 'text-[10px]', barH: 'h-1', pad: 'px-1.5 py-0.5' },
  md: { icon: 'h-4 w-4', text: 'text-xs', barH: 'h-1.5', pad: 'px-2 py-1' },
  lg: { icon: 'h-5 w-5', text: 'text-sm', barH: 'h-2', pad: 'px-2.5 py-1.5' },
} as const;

export default function ConfidenceIndicator({
  score,
  level,
  size = 'md',
  showLabel = true,
  showBar = true,
  className = '',
}: ConfidenceIndicatorProps) {
  const n = normalizeScore(score);
  const resolved = level ?? scoreToLevel(n);
  const meta = LEVEL_META[resolved];
  const Icon = meta.icon;
  const s = SIZE[size];
  const pct = n == null ? null : Math.round(n * 100);

  return (
    <div className={['inline-flex flex-col gap-1 min-w-[7rem]', className].join(' ')}>
      <div
        className={[
          'inline-flex items-center gap-1.5 rounded-lg border w-fit',
          meta.bg,
          s.pad,
        ].join(' ')}
      >
        <Icon className={`${s.icon} ${meta.text}`} />
        {showLabel ? (
          <span className={`${s.text} font-medium ${meta.text}`}>
            {pct != null ? `${pct}%` : meta.label}
          </span>
        ) : null}
      </div>

      {showBar ? (
        <div className={`w-full rounded-full bg-white/5 overflow-hidden ${s.barH}`}>
          <div
            className={`${s.barH} ${meta.bar} rounded-full transition-all duration-300`}
            style={{ width: `${pct ?? 0}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}