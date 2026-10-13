import React, { useCallback, useRef, useState } from 'react';
import {
  Upload,
  FileText,
  FileType,
  FileCode,
  FileImage,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  Shield,
  Trash2,
} from 'lucide-react';
import {
  apiClient,
  MAX_UPLOAD_BYTES,
  type ApiErrorDetails,
  type ScanDocumentResult,
  type UploadResponse,
} from '../lib/apiClient';

const ACCEPTED = '.pdf,.txt,.docx,.doc,.md,.html,.htm,.png,.jpg,.jpeg';

type Stage = 'idle' | 'scanning' | 'uploading' | 'processing' | 'done' | 'error';

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExt(name: string) {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

function FileTypeIcon({
  name,
  className = 'w-6 h-6',
}: {
  name: string;
  className?: string;
}) {
  const ext = fileExt(name);
  if (ext === 'pdf') {
    return <FileText className={`${className} text-red-500`} aria-hidden />;
  }
  if (ext === 'doc' || ext === 'docx') {
    return <FileType className={`${className} text-blue-600`} aria-hidden />;
  }
  if (ext === 'md' || ext === 'html' || ext === 'htm') {
    return <FileCode className={`${className} text-emerald-600`} aria-hidden />;
  }
  if (ext === 'png' || ext === 'jpg' || ext === 'jpeg') {
    return <FileImage className={`${className} text-violet-500`} aria-hidden />;
  }
  return <FileText className={`${className} text-slate-500`} aria-hidden />;
}

function errorMessage(err: unknown): string {
  const e = err as ApiErrorDetails;
  if (e?.code === 'FILE_TOO_LARGE') return String(e.message);
  if (e?.code === 'ECONNABORTED') {
    return 'Request timed out. Try a smaller file or retry.';
  }
  if (typeof e?.message === 'string') return e.message;
  if (e?.message && typeof e.message === 'object') {
    const m = e.message as { detail?: string; error?: string };
    return m.detail || m.error || JSON.stringify(e.message);
  }
  return 'Failed to upload document. Check API URL, CORS, and that the backend is up.';
}

export default function DocumentUpload({
  onUploadSuccess,
}: {
  onUploadSuccess?: (data: UploadResponse) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<Stage>('idle');
  const [dragOver, setDragOver] = useState(false);
  const [status, setStatus] = useState<{
    type: 'success' | 'error' | 'warn';
    message: string;
    extra?: string;
  } | null>(null);

  const validate = (f: File): string | null => {
    if (f.size > MAX_UPLOAD_BYTES) {
      return `File is ${formatBytes(f.size)}; maximum is ${formatBytes(MAX_UPLOAD_BYTES)}.`;
    }
    const ok = ACCEPTED.split(',').some((ext) =>
      f.name.toLowerCase().endsWith(ext.trim())
    );
    if (!ok) {
      return 'Unsupported type. Use PDF, DOC/DOCX, TXT, MD, HTML, or images.';
    }
    return null;
  };

  const pickFile = (f: File | null | undefined) => {
    if (!f) return;
    const err = validate(f);
    if (err) {
      setFile(null);
      setStage('error');
      setStatus({ type: 'error', message: err });
      return;
    }
    setFile(f);
    setStatus(null);
    setStage('idle');
    setProgress(0);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    pickFile(e.target.files?.[0]);
    e.target.value = '';
  };

  const clearFile = useCallback(() => {
    setFile(null);
    setStatus(null);
    setStage('idle');
    setProgress(0);
    if (inputRef.current) inputRef.current.value = '';
  }, []);

  const handleUpload = async () => {
    if (!file || loading) return;

    setLoading(true);
    setStatus(null);
    setProgress(0);

    try {
      // 1) Security scan (optional if endpoint missing)
      setStage('scanning');
      let scan: ScanDocumentResult | undefined;
      try {
        scan = await apiClient.scanDocument(file);
      } catch {
        // continue without blocking upload
      }

      if (scan?.is_flagged) {
        setStage('done');
        setStatus({
          type: 'warn',
          message: `Security scan flagged this file (${scan.status ?? 'quarantined'}, risk ${Number(scan.risk_score ?? 0).toFixed(2)}). Not ingested.`,
          extra: scan.threats_detected?.length
            ? `Threats: ${scan.threats_detected.map(String).join(', ')}`
            : undefined,
        });
        return;
      }

      // 2) Upload with progress
      setStage('uploading');
      const upload = await apiClient.uploadDocument(file, setProgress);

      // 3) Brief processing indicator
      setStage('processing');
      await new Promise((r) => setTimeout(r, 500));

      setStage('done');
      setStatus({
        type: 'success',
        message: upload.message || 'Document uploaded and queued for processing.',
        extra: `ID: ${upload.document_id} · ${upload.status}`,
      });
      setFile(null);
      setProgress(0);
      onUploadSuccess?.(upload);
    } catch (err) {
      console.error(err);
      setStage('error');
      setStatus({ type: 'error', message: errorMessage(err) });
    } finally {
      setLoading(false);
    }
  };

  const stageLabel: Record<Stage, string> = {
    idle: 'Ready',
    scanning: 'Security scan…',
    uploading: 'Uploading…',
    processing: 'Layout analysis (Docling)…',
    done: 'Complete',
    error: 'Failed',
  };

  return (
    <div className="max-w-xl mx-auto p-6 bg-white rounded-xl shadow-md border border-gray-100">
      <h2 className="text-xl font-semibold text-gray-800 mb-1">Upload Document</h2>
      <p className="text-xs text-gray-400 mb-4">
        Security scan → upload → parse · max {formatBytes(MAX_UPLOAD_BYTES)}
      </p>

      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer ${
          dragOver
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-blue-500'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          id="fileInput"
          className="hidden"
          onChange={handleFileChange}
          accept={ACCEPTED}
        />
        <label htmlFor="fileInput" className="cursor-pointer flex flex-col items-center">
          <Upload className="w-12 h-12 text-blue-500 mb-3" />
          <p className="text-sm font-medium text-gray-700">
            Drag & drop your document here, or{' '}
            <span className="text-blue-600 underline">browse</span>
          </p>
          <p className="text-xs text-gray-400 mt-1">
            PDF · DOC/DOCX · TXT · MD · HTML · images
          </p>
        </label>
      </div>

      {/* Selected file */}
      {file && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between gap-3 p-3 bg-blue-50 rounded-lg border border-blue-100">
            <div className="flex items-center space-x-3 truncate min-w-0">
              <FileTypeIcon name={file.name} />
              <div className="truncate min-w-0">
                <div className="text-sm font-medium text-gray-700 truncate">
                  {file.name}
                </div>
                <div className="text-xs text-gray-400">
                  {formatBytes(file.size)}
                  {fileExt(file.name)
                    ? ` · ${fileExt(file.name).toUpperCase()}`
                    : ''}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                type="button"
                onClick={clearFile}
                disabled={loading}
                title="Remove file"
                aria-label="Remove selected file"
                className="inline-flex items-center gap-1 px-2.5 py-2 text-xs font-medium text-rose-600 hover:text-rose-700 hover:bg-rose-50 border border-rose-200 rounded-lg disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4" />
                <span className="hidden sm:inline">Remove</span>
              </button>

              <button
                type="button"
                onClick={() => void handleUpload()}
                disabled={loading}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors flex items-center space-x-2 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Shield className="w-4 h-4" />
                )}
                <span>{loading ? stageLabel[stage] : 'Scan & Upload'}</span>
              </button>
            </div>
          </div>

          {loading && (
            <>
              {(stage === 'uploading' || progress > 0) && (
                <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-blue-600 h-2 transition-all duration-200"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              )}
              <ol className="flex flex-wrap gap-2 text-xs">
                {(['scanning', 'uploading', 'processing'] as Stage[]).map((s) => {
                  const order = ['scanning', 'uploading', 'processing'];
                  const active = stage === s;
                  const done = order.indexOf(stage) > order.indexOf(s);
                  return (
                    <li
                      key={s}
                      className={`px-2.5 py-1 rounded-full border ${
                        active
                          ? 'border-blue-500 text-blue-700 bg-blue-50'
                          : done
                            ? 'border-green-500 text-green-700 bg-green-50'
                            : 'border-gray-200 text-gray-400'
                      }`}
                    >
                      {active && (
                        <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                      )}
                      {stageLabel[s]}
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </div>
      )}

      {/* Status banner */}
      {status && (
        <div
          className={`mt-4 p-3 rounded-lg flex items-start space-x-2 text-sm ${
            status.type === 'success'
              ? 'bg-green-50 text-green-700 border border-green-100'
              : status.type === 'warn'
                ? 'bg-amber-50 text-amber-800 border border-amber-100'
                : 'bg-red-50 text-red-700 border border-red-100'
          }`}
        >
          {status.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            <div>{status.message}</div>
            {status.extra && (
              <div className="text-xs mt-1 opacity-80 font-mono break-all">
                {status.extra}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => setStatus(null)}
            className="p-1 text-current opacity-50 hover:opacity-100"
            aria-label="Dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}