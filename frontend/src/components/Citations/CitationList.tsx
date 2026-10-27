/**
 * CitationList — ordered list of RAG citations with empty / loading states.
 */
import React from 'react';
import { Library } from 'lucide-react';
import CitationCard, { Citation } from './CitationCard';

export type CitationListProps = {
  citations: Citation[];
  loading?: boolean;
  title?: string;
  emptyMessage?: string;
  maxVisible?: number;
  onSelect?: (citation: Citation) => void;
  className?: string;
};

export default function CitationList({
  citations,
  loading = false,
  title = 'Sources',
  emptyMessage = 'No citations for this answer.',
  maxVisible,
  onSelect,
  className = '',
}: CitationListProps) {
  const list =
    maxVisible != null ? citations.slice(0, maxVisible) : citations;
  const hidden =
    maxVisible != null ? Math.max(0, citations.length - maxVisible) : 0;

  return (
    <section className={['space-y-3', className].join(' ')}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Library className="h-4 w-4 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400">
            {citations.length}
          </span>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-xl border border-white/5 bg-slate-800/50"
            />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 bg-slate-900/40 px-4 py-8 text-center text-sm text-slate-500">
          {emptyMessage}
        </div>
      ) : (
        <ul className="space-y-2">
          {list.map((c, i) => (
            <li key={c.id || c.document_id || `${getKey(c)}-${i}`}>
              <CitationCard
                citation={c}
                rank={i + 1}
                onSelect={onSelect}
              />
            </li>
          ))}
        </ul>
      )}

      {hidden > 0 ? (
        <p className="text-xs text-slate-500">+{hidden} more source(s)</p>
      ) : null}
    </section>
  );
}

function getKey(c: Citation): string {
  return c.file_name || c.source || c.title || 'src';
}