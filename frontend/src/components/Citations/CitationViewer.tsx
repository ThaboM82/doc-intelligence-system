/**
 * CitationViewer — side panel / modal-style detail view for one citation.
 */
import React, { useEffect } from 'react';
import { X, ExternalLink, FileSearch } from 'lucide-react';
import SourceBadge from './SourceBadge';
import ConfidenceIndicator from './ConfidenceIndicator';
import type { Citation } from './CitationCard';

export type CitationViewerProps = {
  citation: Citation | null;
  open: boolean;
  onClose: () => void;
  /** Optional link builder for "open document" */
  documentHref?: (citation: Citation) => string | undefined;
  className?: string;
};

export default function CitationViewer({
  citation,
  open,
  onClose,
  documentHref,
  className = '',
}: CitationViewerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !citation) return null;

  const label =
    citation.file_name ||
    citation.source ||
    citation.title ||
    citation.document_id ||
    'Source';
  const body = (
    citation.text ||
    citation.content ||
    citation.snippet ||
    ''
  ).trim();
  const href = documentHref?.(citation);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label="Citation detail"
      onClick={onClose}
    >
      <div
        className={[
          'flex h-full w-full max-w-lg flex-col border-l border-white/10 bg-slate-950 shadow-2xl',
          className,
        ].join(' ')}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-white/10 px-5 py-4">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2 text-slate-400">
              <FileSearch className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wider">
                Citation
              </span>
            </div>
            <SourceBadge
              label={label}
              kind={citation.kind}
              page={citation.page}
              score={citation.score}
              truncated={false}
            />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-white/5 p-2 text-slate-400 hover:text-slate-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <ConfidenceIndicator score={citation.score} size="md" showBar />

          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Excerpt
            </h4>
            <div className="rounded-xl border border-white/10 bg-slate-900/80 p-4 text-sm leading-relaxed text-slate-200 whitespace-pre-wrap">
              {body || 'No text available for this chunk.'}
            </div>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-xs">
            {citation.document_id ? (
              <div className="rounded-lg border border-white/5 bg-white/[0.03] p-2">
                <dt className="text-slate-500">Document ID</dt>
                <dd className="mt-0.5 break-all text-slate-300">
                  {citation.document_id}
                </dd>
              </div>
            ) : null}
            {citation.chunk_index != null ? (
              <div className="rounded-lg border border-white/5 bg-white/[0.03] p-2">
                <dt className="text-slate-500">Chunk</dt>
                <dd className="mt-0.5 text-slate-300">{citation.chunk_index}</dd>
              </div>
            ) : null}
            {citation.page != null ? (
              <div className="rounded-lg border border-white/5 bg-white/[0.03] p-2">
                <dt className="text-slate-500">Page</dt>
                <dd className="mt-0.5 text-slate-300">{citation.page}</dd>
              </div>
            ) : null}
            {citation.id ? (
              <div className="rounded-lg border border-white/5 bg-white/[0.03] p-2">
                <dt className="text-slate-500">Point ID</dt>
                <dd className="mt-0.5 break-all text-slate-300">{citation.id}</dd>
              </div>
            ) : null}
          </dl>
        </div>

        {href ? (
          <footer className="border-t border-white/10 px-5 py-3">
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-sm font-medium text-blue-300 hover:bg-blue-500/20"
            >
              <ExternalLink className="h-4 w-4" />
              Open document
            </a>
          </footer>
        ) : null}
      </div>
    </div>
  );
}