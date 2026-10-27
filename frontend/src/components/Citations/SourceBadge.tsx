/**
 * SourceBadge — compact file/source chip for RAG citations.
 */
import React from 'react';
import { FileText, File, Link2, BookOpen } from 'lucide-react';

export type SourceKind = 'pdf' | 'txt' | 'md' | 'html' | 'url' | 'doc' | 'unknown';

export type SourceBadgeProps = {
  label: string;
  kind?: SourceKind;
  score?: number;
  page?: number | string;
  truncated?: boolean;
  onClick?: () => void;
  className?: string;
};

function detectKind(label: string, kind?: SourceKind): SourceKind {
  if (kind && kind !== 'unknown') return kind;
  const l = label.toLowerCase();
  if (l.endsWith('.pdf')) return 'pdf';
  if (l.endsWith('.md') || l.endsWith('.markdown')) return 'md';
  if (l.endsWith('.html') || l.endsWith('.htm')) return 'html';
  if (l.endsWith('.txt') || l.endsWith('.csv') || l.endsWith('.log')) return 'txt';
  if (l.startsWith('http://') || l.startsWith('https://')) return 'url';
  if (l.endsWith('.doc') || l.endsWith('.docx')) return 'doc';
  return 'unknown';
}

const KIND_STYLE: Record<
  SourceKind,
  { icon: typeof FileText; chip: string; iconColor: string }
> = {
  pdf: {
    icon: FileText,
    chip: 'border-rose-500/25 bg-rose-500/10',
    iconColor: 'text-rose-400',
  },
  txt: {
    icon: File,
    chip: 'border-slate-500/25 bg-slate-500/10',
    iconColor: 'text-slate-300',
  },
  md: {
    icon: BookOpen,
    chip: 'border-violet-500/25 bg-violet-500/10',
    iconColor: 'text-violet-400',
  },
  html: {
    icon: FileText,
    chip: 'border-amber-500/25 bg-amber-500/10',
    iconColor: 'text-amber-400',
  },
  url: {
    icon: Link2,
    chip: 'border-cyan-500/25 bg-cyan-500/10',
    iconColor: 'text-cyan-400',
  },
  doc: {
    icon: FileText,
    chip: 'border-blue-500/25 bg-blue-500/10',
    iconColor: 'text-blue-400',
  },
  unknown: {
    icon: File,
    chip: 'border-white/10 bg-white/5',
    iconColor: 'text-slate-400',
  },
};

export default function SourceBadge({
  label,
  kind,
  score,
  page,
  truncated = true,
  onClick,
  className = '',
}: SourceBadgeProps) {
  const k = detectKind(label, kind);
  const meta = KIND_STYLE[k];
  const Icon = meta.icon;
  const interactive = Boolean(onClick);

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!interactive}
      className={[
        'inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2 py-1 text-left text-[11px] font-medium text-slate-200',
        meta.chip,
        interactive
          ? 'cursor-pointer hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40'
          : 'cursor-default',
        className,
      ].join(' ')}
      title={label}
    >
      <Icon className={`h-3.5 w-3.5 shrink-0 ${meta.iconColor}`} />
      <span className={truncated ? 'truncate' : ''}>{label}</span>
      {page != null && page !== '' ? (
        <span className="shrink-0 text-slate-500">p.{page}</span>
      ) : null}
      {typeof score === 'number' ? (
        <span className="shrink-0 rounded bg-black/20 px-1 text-[10px] text-slate-400">
          {(score <= 1 ? score * 100 : score).toFixed(0)}%
        </span>
      ) : null}
    </button>
  );
}