/**
 * DocumentManager — list / search / delete ingested documents.
 * GET /api/v1/documents (and fallbacks) + local session library.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FileText,
  Trash2,
  RefreshCcw,
  AlertCircle,
  Search,
  Database,
  HardDrive,
  ShieldCheck,
  Loader2,
  FileCode,
  FileSpreadsheet,
  File,
} from 'lucide-react';
import { apiClient } from '../lib/apiClient';

export type ManagedDoc = {
  id: string;
  document_id?: string;
  filename: string;
  text_snippet?: string;
  status?: string;
  chunks?: number;
  chunks_upserted?: number;
  security_scan_passed?: boolean;
  metadata?: Record<string, unknown>;
  uploaded_at?: number | string;
};

const LOCAL_LIBRARY_KEY = 'doc_intel_library_v1';

function readLocalLibrary(): ManagedDoc[] {
  try {
    const raw = localStorage.getItem(LOCAL_LIBRARY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Array<{
      document_id: string;
      filename: string;
      status?: string;
      chunks_upserted?: number;
      security_scan_passed?: boolean;
      message?: string;
      uploaded_at?: number;
    }>;
    if (!Array.isArray(parsed)) return [];
    return parsed.map((d) => ({
      id: d.document_id,
      document_id: d.document_id,
      filename: d.filename,
      status: d.status,
      chunks_upserted: d.chunks_upserted,
      security_scan_passed: d.security_scan_passed,
      text_snippet: d.message,
      uploaded_at: d.uploaded_at,
      metadata: {},
    }));
  } catch {
    return [];
  }
}

function writeLocalLibrary(docs: ManagedDoc[]) {
  try {
    const payload = docs.map((d) => ({
      document_id: d.document_id || d.id,
      filename: d.filename,
      status: d.status,
      chunks_upserted: d.chunks_upserted ?? d.chunks,
      security_scan_passed: d.security_scan_passed,
      message: d.text_snippet,
      uploaded_at:
        typeof d.uploaded_at === 'number' ? d.uploaded_at : Date.now(),
    }));
    localStorage.setItem(LOCAL_LIBRARY_KEY, JSON.stringify(payload.slice(0, 50)));
    window.dispatchEvent(new Event('doc-library-updated'));
  } catch {
    /* ignore */
  }
}

function errorMessage(err: unknown): string {
  const e = err as { message?: unknown; detail?: unknown; code?: string };
  if (e?.code === 'CIRCUIT_OPEN') {
    return 'API circuit is open. Wait and retry (Render may be waking up).';
  }
  const d = e?.detail ?? e?.message;
  if (typeof d === 'string') return d;
  if (d) {
    try {
      return JSON.stringify(d);
    } catch {
      /* ignore */
    }
  }
  return 'Could not reach the document API.';
}

function normalizeListPayload(data: unknown): ManagedDoc[] {
  if (!data) return [];
  if (Array.isArray(data)) {
    return data.map((item, i) => {
      const row = item as Record<string, unknown>;
      const id = String(row.id ?? row.document_id ?? row.point_id ?? `row-${i}`);
      return {
        id,
        document_id: String(row.document_id ?? id),
        filename: String(
          row.filename ?? row.file_name ?? row.title ?? 'document'
        ),
        text_snippet: String(
          row.text_snippet ?? row.snippet ?? row.text ?? row.message ?? ''
        ).slice(0, 240),
        status: row.status != null ? String(row.status) : undefined,
        chunks:
          typeof row.chunks === 'number'
            ? row.chunks
            : typeof row.chunks_upserted === 'number'
              ? row.chunks_upserted
              : undefined,
        chunks_upserted:
          typeof row.chunks_upserted === 'number'
            ? row.chunks_upserted
            : undefined,
        security_scan_passed:
          typeof row.security_scan_passed === 'boolean'
            ? row.security_scan_passed
            : undefined,
        metadata:
          row.metadata && typeof row.metadata === 'object'
            ? (row.metadata as Record<string, unknown>)
            : {},
        uploaded_at: (row.uploaded_at ?? row.created_at) as
          | number
          | string
          | undefined,
      };
    });
  }
  const obj = data as Record<string, unknown>;
  if (Array.isArray(obj.documents)) return normalizeListPayload(obj.documents);
  if (Array.isArray(obj.items)) return normalizeListPayload(obj.items);
  if (Array.isArray(obj.points)) return normalizeListPayload(obj.points);
  return [];
}

function fileIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['csv', 'xlsx', 'xls'].includes(ext)) return FileSpreadsheet;
  if (['json', 'md', 'html', 'htm', 'txt', 'log'].includes(ext)) return FileCode;
  if (['pdf', 'doc', 'docx'].includes(ext)) return FileText;
  return File;
}

function formatWhen(v?: number | string) {
  if (v == null) return '';
  try {
    const n = typeof v === 'number' ? v : Date.parse(String(v));
    if (!Number.isFinite(n)) return String(v);
    // seconds vs ms
    const ms = n < 1e12 ? n * 1000 : n;
    return new Date(ms).toLocaleString();
  } catch {
    return String(v);
  }
}

export default function DocumentManager() {
  const [documents, setDocuments] = useState<ManagedDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [source, setSource] = useState<'api' | 'local' | 'mixed'>('api');
  const [stats, setStats] = useState<{ points?: number; status?: string } | null>(
    null
  );

  const collectionHint =
    (import.meta.env.VITE_QDRANT_COLLECTION as string | undefined) ||
    'document_intelligence';

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);

    let apiDocs: ManagedDoc[] = [];
    let usedApi = false;

    const listCandidates = [
      '/api/v1/documents',
      '/api/v1/intelligence/documents',
      '/api/v1/admin/documents',
    ];

    for (const path of listCandidates) {
      try {
        const data = await apiClient.get(path);
        apiDocs = normalizeListPayload(data);
        usedApi = true;
        break;
      } catch {
        /* try next */
      }
    }

    try {
      if (typeof apiClient.getCollectionStats === 'function') {
        const s = await apiClient.getCollectionStats();
        setStats({
          points: s.points_count ?? s.vectors_count ?? s.document_count,
          status: s.status,
        });
      }
    } catch {
      /* optional */
    }

    const local = readLocalLibrary();

    if (usedApi && apiDocs.length > 0) {
      setDocuments(apiDocs);
      setSource('api');
    } else if (usedApi && local.length > 0) {
      setDocuments(local);
      setSource('mixed');
      setError(
        'List API returned empty — showing browser session library. Upload more or wait for indexing.'
      );
    } else if (!usedApi && local.length > 0) {
      setDocuments(local);
      setSource('local');
      setError(
        'Document list API not available — showing uploads from this browser session.'
      );
    } else if (!usedApi) {
      setDocuments([]);
      setSource('local');
      setError(
        'No document list endpoint found. Add GET /api/v1/documents on the backend, or upload to build a local list.'
      );
    } else {
      setDocuments([]);
      setSource('api');
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    void fetchDocuments();
    const onLib = () => void fetchDocuments();
    window.addEventListener('doc-library-updated', onLib);
    return () => window.removeEventListener('doc-library-updated', onLib);
  }, [fetchDocuments]);

  const handleDelete = async (doc: ManagedDoc) => {
    const id = doc.document_id || doc.id;
    if (
      !window.confirm(
        `Remove document "${doc.filename}" (${id}) from the store / library?`
      )
    ) {
      return;
    }

    setDeletingId(id);
    try {
      if (typeof apiClient.deleteDocument === 'function') {
        await apiClient.deleteDocument(id);
      } else {
        await apiClient.delete(`/api/v1/documents/${encodeURIComponent(id)}`);
      }
      setDocuments((prev) => {
        const next = prev.filter((d) => (d.document_id || d.id) !== id);
        writeLocalLibrary(next);
        return next;
      });
    } catch (err) {
      setDocuments((prev) => {
        const next = prev.filter((d) => (d.document_id || d.id) !== id);
        writeLocalLibrary(next);
        return next;
      });
      setError(
        `${errorMessage(err)} — Removed from local library; server may still hold vectors.`
      );
    } finally {
      setDeletingId(null);
    }
  };

  const filteredDocuments = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter(
      (doc) =>
        doc.filename?.toLowerCase().includes(q) ||
        doc.text_snippet?.toLowerCase().includes(q) ||
        doc.id?.toLowerCase().includes(q) ||
        String(doc.metadata?.source ?? '')
          .toLowerCase()
          .includes(q)
    );
  }, [documents, searchTerm]);

  const vectorCountLabel =
    stats?.points != null ? String(stats.points) : String(documents.length);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-slate-100 flex items-center space-x-2">
            <Database className="w-5 h-5 text-blue-400" />
            <span>Ingested document management</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Collection{' '}
            <span className="text-blue-400 font-mono">{collectionHint}</span>
            {source !== 'api' && (
              <span className="text-amber-400/90"> · source: {source}</span>
            )}
          </p>
        </div>

        <div className="flex items-center space-x-3 flex-wrap">
          <div className="text-xs bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg text-slate-300 flex items-center space-x-1.5">
            <HardDrive className="w-3.5 h-3.5 text-blue-400" />
            <span>
              Points / rows:{' '}
              <strong className="text-slate-100">{vectorCountLabel}</strong>
            </span>
          </div>
          {stats?.status && (
            <div className="text-xs bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg text-slate-300 flex items-center space-x-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>{stats.status}</span>
            </div>
          )}

          <button
            type="button"
            onClick={() => void fetchDocuments()}
            disabled={loading}
            className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition flex items-center space-x-1.5 text-xs font-medium border border-slate-700/60 disabled:opacity-50"
            title="Refresh list"
          >
            <RefreshCcw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <div className="relative">
        <Search className="absolute left-3.5 top-3 w-4 h-4 text-slate-500" />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Filter by filename, id, or snippet…"
          className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-10 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition"
        />
      </div>

      {error && (
        <div className="p-4 bg-amber-950/30 border border-amber-800/40 rounded-lg flex items-start space-x-3 text-amber-200 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 text-amber-400 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {loading && documents.length === 0 ? (
        <div className="py-16 text-center text-slate-500 text-sm flex flex-col items-center justify-center space-y-2">
          <RefreshCcw className="w-6 h-6 animate-spin text-blue-500" />
          <span>Loading documents…</span>
        </div>
      ) : filteredDocuments.length === 0 ? (
        <div className="py-16 text-center border border-dashed border-slate-800 rounded-xl">
          <FileText className="w-10 h-10 text-slate-600 mx-auto mb-2" />
          <p className="text-sm font-medium text-slate-300">
            {searchTerm ? 'No matching documents' : 'No documents yet'}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {searchTerm
              ? 'Try another search.'
              : 'Upload via the ingestion pipeline to populate this list.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto border border-slate-800 rounded-lg">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-xs font-medium text-slate-400 uppercase tracking-wider">
                <th className="py-3 px-4">Filename / ID</th>
                <th className="py-3 px-4">Snippet</th>
                <th className="py-3 px-4">Tags</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-sm">
              {filteredDocuments.map((doc) => {
                const id = doc.document_id || doc.id;
                const chunks = doc.chunks_upserted ?? doc.chunks;
                const Icon = fileIcon(doc.filename);
                return (
                  <tr key={id} className="hover:bg-slate-800/40 transition">
                    <td className="py-3.5 px-4 font-medium text-slate-200">
                      <div className="flex items-center space-x-2">
                        <Icon className="w-4 h-4 text-blue-400 flex-shrink-0" />
                        <span className="truncate max-w-[200px]" title={doc.filename}>
                          {doc.filename}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono mt-0.5 truncate max-w-[240px]">
                        {id}
                      </div>
                      {doc.status && (
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {doc.status}
                          {doc.uploaded_at != null
                            ? ` · ${formatWhen(doc.uploaded_at)}`
                            : ''}
                        </div>
                      )}
                    </td>

                    <td className="py-3.5 px-4 text-slate-400 max-w-xs truncate text-xs font-mono">
                      {doc.text_snippet || '—'}
                    </td>

                    <td className="py-3.5 px-4">
                      <div className="flex flex-wrap gap-1">
                        <span className="text-[10px] bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded font-mono">
                          {chunks != null ? `${chunks} chunks` : 'doc'}
                        </span>
                        {doc.security_scan_passed === true && (
                          <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-mono">
                            scan ok
                          </span>
                        )}
                        {doc.security_scan_passed === false && (
                          <span className="text-[10px] bg-rose-500/10 text-rose-400 border border-rose-500/20 px-2 py-0.5 rounded font-mono">
                            flagged
                          </span>
                        )}
                        {doc.metadata?.source != null && (
                          <span className="text-[10px] bg-slate-800 text-slate-300 border border-slate-700 px-2 py-0.5 rounded font-mono truncate max-w-[120px]">
                            {String(doc.metadata.source)}
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="py-3.5 px-4 text-right">
                      <button
                        type="button"
                        onClick={() => void handleDelete(doc)}
                        disabled={deletingId === id}
                        className="px-2.5 py-1.5 bg-red-600/10 hover:bg-red-600/20 text-red-400 border border-red-500/20 rounded-lg transition inline-flex items-center space-x-1.5 text-xs font-medium disabled:opacity-50"
                        title="Delete document"
                      >
                        {deletingId === id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="w-3.5 h-3.5" />
                        )}
                        <span>{deletingId === id ? 'Deleting…' : 'Delete'}</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}