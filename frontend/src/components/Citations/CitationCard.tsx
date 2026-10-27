/**
 * CitationCard — single retrieved chunk / source for RAG answers.
 */
import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Quote, Copy, Check } from 'lucide-react';
import SourceBadge, { SourceKind } from './SourceBadge';
import ConfidenceIndicator from './ConfidenceIndicator';

export type Citation = {
  id?: string;
  index?: number;
  file_name?: string;
  source?: string;
  title?: string;
  text?: string;
  content?: string;
  snippet?: string;
  score?: number;
  page?: number | string;
  chunk_index?: number;
  document_id?: string;
  kind?: SourceKind;
  metadata?: Record<string, unknown>;
};

export type CitationCardProps = {
  citation: Citation;
  rank?: number;
  defaultExpanded?: boolean;
  onSelect?: (citation: Citation) => void;
  className?: string;
};

function getLabel(c: Citation): string {
  return (
    c.file_name ||
    c.source ||
    c.title ||
    c.document_id ||
    c.id ||
    'Source'
  );
}

function getText(c: Citation): string {
  return (c.text || c.content || c.snippet || '').trim();
}

export default function CitationCard({
  citation,
  rank,
  defaultExpanded = false,
  onSelect,
  className = '',
}: CitationCardProps) {
  const [open, setOpen] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);
  const label = getLabel(citation);
  const text = getText(citation);
  const preview =
    text.length > 220 && !open ? `${text.slice(0, 220).trim()}…` : text;

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(text || label);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <article
      className={[
        'rounded-xl border border-white/10 bg-slate-900/70 backdrop-blur-sm',
        'p-4 shadow-md transition hover:border-white/15',
        className,
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          {rank != null ? (
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[11px] font-semibold text-slate-300">
              {rank}
            </span>
          ) : (
            <Quote className="mt-1 h-4 w-4 shrink-0 text-slate-500" />
          )}

          <div className="min-w-0 flex-1 space-y-2">
            <SourceBadge
              label={label}
              kind={citation.kind}
              score={citation.score}
              page={citation.page}
              onClick={onSelect ? () => onSelect(citation) : undefined}
            />

            {text ? (
              <p className="text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">
                {preview || 'No excerpt available.'}
              </p>
            ) : (
              <p className="text-sm text-slate-500 italic">No excerpt available.</p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <ConfidenceIndicator
            score={citation.score}
            size="sm"
            showBar={false}
            showLabel
          />
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={copyText}
              className="rounded-md border border-white/10 bg-white/5 p-1.5 text-slate-400 hover:text-slate-200"
              title="Copy excerpt"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
            {text.length > 220 ? (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="rounded-md border border-white/10 bg-white/5 p-1.5 text-slate-400 hover:text-slate-200"
                title={open ? 'Collapse' : 'Expand'}
              >
                {open ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {(citation.chunk_index != null || citation.document_id) && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-white/5 pt-2 text-[10px] text-slate-500">
          {citation.document_id ? (
            <span>doc: {citation.document_id}</span>
          ) : null}
          {citation.chunk_index != null ? (
            <span>chunk: {citation.chunk_index}</span>
          ) : null}
        </div>
      )}
    </article>
  );
}