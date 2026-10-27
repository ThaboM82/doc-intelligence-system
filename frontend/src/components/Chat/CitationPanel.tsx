import { useEffect, useRef } from "react";
import {
  X, FileText, Hash, BookOpen, BarChart2, Layers,
} from "lucide-react";
import type { Citation } from "./types";

interface CitationPanelProps {
  citation: Citation | null;
  open: boolean;
  onClose: () => void;
}

const CitationPanel = ({ citation, open, onClose }: CitationPanelProps) => {
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open, citation]);

  if (!open || !citation) return null;

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]"
        aria-label="Close citation panel"
        onClick={onClose}
      />

      <aside
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="citation-panel-title"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-slate-700 bg-slate-900 shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-700 px-5 py-4">
          <div className="flex items-start gap-3 min-w-0">
            <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-indigo-400/20 bg-indigo-500/15 text-indigo-300">
              <BookOpen size={18} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2
                id="citation-panel-title"
                className="truncate text-base font-semibold text-slate-100"
              >
                [{citation.n}] {citation.fileName || citation.title || "Source"}
              </h2>
              <p className="mt-0.5 text-xs text-slate-400">Citation details</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
            aria-label="Close"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          <MetaRow icon={<Hash size={14} />} label="Citation index" value={`#${citation.n}`} />
          {citation.fileName && (
            <MetaRow icon={<FileText size={14} />} label="File" value={citation.fileName} />
          )}
          {citation.title && citation.title !== citation.fileName && (
            <MetaRow icon={<Layers size={14} />} label="Title" value={citation.title} />
          )}
          {citation.page != null && (
            <MetaRow icon={<BookOpen size={14} />} label="Page" value={String(citation.page)} />
          )}
          {citation.score != null && (
            <MetaRow
              icon={<BarChart2 size={14} />}
              label="Relevance score"
              value={citation.score.toFixed(4)}
            />
          )}
          {citation.documentId && (
            <MetaRow icon={<Hash size={14} />} label="Document ID" value={citation.documentId} />
          )}

          {citation.text && (
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Excerpt
              </p>
              <blockquote className="rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm leading-relaxed text-slate-300">
                {citation.text}
              </blockquote>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};

function MetaRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 text-slate-500" aria-hidden="true">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </dt>
        <dd className="mt-0.5 break-all text-sm font-medium text-slate-200">
          {value}
        </dd>
      </div>
    </div>
  );
}

export default CitationPanel;