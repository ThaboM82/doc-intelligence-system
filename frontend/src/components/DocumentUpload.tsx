/**
 * DocumentUpload — bulk drag/drop, queue, cancel, retry failed.
 * Drop into: frontend/src/components/DocumentUpload.tsx
 */
import React, { useCallback, useId, useRef, useState } from "react";
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
  Square,
  AlertTriangle,
  Files,
  RotateCcw,
} from "lucide-react";
import {
  apiClient,
  MAX_UPLOAD_BYTES,
  type ApiErrorDetails,
  type ScanDocumentResult,
  type UploadResponse,
} from "../lib/apiClient";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACCEPTED =
  ".pdf,.txt,.docx,.doc,.md,.html,.htm,.png,.jpg,.jpeg,.csv,.json";

const MAX_BULK_FILES = 20;

type FileJobStatus =
  | "queued"
  | "scanning"
  | "uploading"
  | "processing"
  | "success"
  | "quarantined"
  | "error"
  | "cancelled";

type FileJob = {
  id: string;
  file: File;
  status: FileJobStatus;
  progress: number;
  message?: string;
  errorCode?: string;
  response?: UploadResponse;
};

export type UploadSuccessPayload = UploadResponse & {
  document_id?: string;
  filename?: string;
  status?: string;
  message?: string;
  chunks_upserted?: number;
  security_scan_passed?: boolean;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function newJobId() {
  return `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExt(name: string) {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

function FileTypeIcon({
  name,
  className = "h-5 w-5",
}: {
  name: string;
  className?: string;
}) {
  const ext = fileExt(name);
  if (ext === "pdf") {
    return <FileText className={`${className} text-red-500`} aria-hidden />;
  }
  if (ext === "doc" || ext === "docx") {
    return <FileType className={`${className} text-blue-600`} aria-hidden />;
  }
  if (ext === "md" || ext === "html" || ext === "htm" || ext === "json") {
    return <FileCode className={`${className} text-emerald-600`} aria-hidden />;
  }
  if (ext === "png" || ext === "jpg" || ext === "jpeg") {
    return <FileImage className={`${className} text-violet-500`} aria-hidden />;
  }
  return <FileText className={`${className} text-slate-500`} aria-hidden />;
}

function isCancelled(err: unknown): boolean {
  const e = err as { code?: string; name?: string };
  return (
    e?.code === "ERR_CANCELED" ||
    e?.name === "AbortError" ||
    e?.name === "CanceledError"
  );
}

/** Map API / network failures to a clear user message + code */
function classifyUploadError(err: unknown): { message: string; code?: string } {
  const e = err as ApiErrorDetails & {
    response?: { status?: number; data?: { detail?: unknown } };
  };

  if (isCancelled(err)) {
    return { message: "Cancelled.", code: "ERR_CANCELED" };
  }

  const status = e?.status ?? e?.response?.status;
  const code = e?.code;

  if (code === "FILE_TOO_LARGE" || status === 413) {
    return {
      message:
        typeof e?.message === "string"
          ? e.message
          : `File exceeds ${formatBytes(MAX_UPLOAD_BYTES)}.`,
      code: "FILE_TOO_LARGE",
    };
  }
  if (code === "CIRCUIT_OPEN" || status === 503) {
    return {
      message: "Service temporarily unavailable (circuit open). Retry shortly.",
      code: "CIRCUIT_OPEN",
    };
  }
  if (code === "ECONNABORTED" || code === "ETIMEDOUT") {
    return {
      message: "Request timed out. Try a smaller file or retry.",
      code: code,
    };
  }
  if (code === "ERR_NETWORK" || code === "ENOTFOUND") {
    return {
      message: "Network error. Check API URL, CORS, and connectivity.",
      code: "ERR_NETWORK",
    };
  }
  if (status === 401) {
    return {
      message: "Unauthorized. Sign in or paste a valid JWT (key icon).",
      code: "UNAUTHORIZED",
    };
  }
  if (status === 403) {
    return {
      message: "Forbidden. Your role may lack upload permission.",
      code: "FORBIDDEN",
    };
  }
  if (status === 415) {
    return {
      message: "Unsupported media type for this endpoint.",
      code: "UNSUPPORTED_TYPE",
    };
  }
  if (status === 429) {
    return {
      message: "Rate limited. Wait a moment and retry failed files.",
      code: "RATE_LIMIT",
    };
  }
  if (status && status >= 500) {
    return {
      message: `Server error (${status}). Retry later.`,
      code: "SERVER_ERROR",
    };
  }

  let message = "Upload failed.";
  if (typeof e?.message === "string" && e.message.trim()) {
    message = e.message;
  } else if (e?.message && typeof e.message === "object") {
    const m = e.message as { detail?: string; error?: string };
    message = m.detail || m.error || JSON.stringify(e.message);
  } else if (e?.detail != null) {
    message =
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail);
  }

  return { message, code: code || (status ? `HTTP_${status}` : undefined) };
}

function validateFile(f: File): string | null {
  if (f.size <= 0) return "Empty file.";
  if (f.size > MAX_UPLOAD_BYTES) {
    return `Exceeds ${formatBytes(MAX_UPLOAD_BYTES)} (${formatBytes(f.size)}).`;
  }
  const ok = ACCEPTED.split(",").some((ext) =>
    f.name.toLowerCase().endsWith(ext.trim())
  );
  if (!ok) return "Unsupported type.";
  return null;
}

function StatusLabel({ status }: { status: FileJobStatus }) {
  const map: Record<FileJobStatus, string> = {
    queued: "Queued",
    scanning: "Scanning",
    uploading: "Uploading",
    processing: "Processing",
    success: "Uploaded",
    quarantined: "Quarantined",
    error: "Failed",
    cancelled: "Cancelled",
  };
  return <span>{map[status]}</span>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DocumentUpload({
  onUploadSuccess,
}: {
  onUploadSuccess?: (data: UploadSuccessPayload) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const cancelAllRef = useRef(false);
  const dragDepthRef = useRef(0);
  const inputId = useId();

  const [jobs, setJobs] = useState<FileJob[]>([]);
  const [running, setRunning] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [banner, setBanner] = useState<{
    type: "success" | "error" | "warn" | "info";
    message: string;
  } | null>(null);

  const updateJob = useCallback((id: string, patch: Partial<FileJob>) => {
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)));
  }, []);

  const addFiles = useCallback(
    (list: FileList | File[] | null | undefined) => {
      if (!list || running) return;
      const incoming = Array.from(list);
      if (!incoming.length) return;

      setBanner(null);

      setJobs((prev) => {
        const room = Math.max(0, MAX_BULK_FILES - prev.length);
        const slice = incoming.slice(0, room);
        const next: FileJob[] = slice.map((file) => {
          const err = validateFile(file);
          return {
            id: newJobId(),
            file,
            status: err ? ("error" as const) : ("queued" as const),
            progress: 0,
            message: err || undefined,
            errorCode: err ? "VALIDATION" : undefined,
          };
        });

        if (incoming.length > room) {
          queueMicrotask(() =>
            setBanner({
              type: "warn",
              message: `Only ${MAX_BULK_FILES} files allowed at once. Extra files were skipped.`,
            })
          );
        }
        return [...prev, ...next];
      });
    },
    [running]
  );

  const removeJob = (id: string) => {
    if (running) return;
    setJobs((prev) => prev.filter((j) => j.id !== id));
  };

  const clearAll = () => {
    if (running) return;
    setJobs([]);
    setBanner(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const retryFailed = () => {
    if (running) return;
    setJobs((prev) =>
      prev.map((j) =>
        j.status === "error"
          ? {
              ...j,
              status: "queued" as const,
              progress: 0,
              message: undefined,
              errorCode: undefined,
              response: undefined,
            }
          : j
      )
    );
    setBanner({
      type: "info",
      message: "Failed files re-queued. Click Scan & upload.",
    });
  };

  const cancelAll = () => {
    cancelAllRef.current = true;
    abortRef.current?.abort();
    abortRef.current = null;
    setJobs((prev) =>
      prev.map((j) =>
        ["queued", "scanning", "uploading", "processing"].includes(j.status)
          ? { ...j, status: "cancelled" as const, message: "Cancelled." }
          : j
      )
    );
    setRunning(false);
    setBanner({ type: "info", message: "Bulk upload cancelled." });
  };

  // ---- Drag and drop (depth counter avoids flicker) ----
  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (running) return;
    dragDepthRef.current += 1;
    setDragOver(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragOver(false);
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!running) {
      e.dataTransfer.dropEffect = "copy";
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepthRef.current = 0;
    setDragOver(false);
    if (running) return;

    const dt = e.dataTransfer;
    const files: File[] = [];

    if (dt.files?.length) {
      files.push(...Array.from(dt.files));
    } else if (dt.items?.length) {
      for (const item of Array.from(dt.items)) {
        if (item.kind === "file") {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
    }

    if (!files.length) {
      setBanner({
        type: "warn",
        message:
          "Drop did not include any files. Try dragging files from disk.",
      });
      return;
    }
    addFiles(files);
  };

  const processOne = async (job: FileJob, signal: AbortSignal) => {
    const { file, id } = job;

    updateJob(id, {
      status: "scanning",
      progress: 0,
      message: undefined,
      errorCode: undefined,
    });

    let scan: ScanDocumentResult | undefined;
    try {
      scan = await apiClient.scanDocument(file, undefined, signal);
    } catch (err) {
      if (isCancelled(err) || cancelAllRef.current) {
        updateJob(id, { status: "cancelled", message: "Cancelled." });
        return;
      }
      // Scan optional — continue to upload
    }

    if (scan?.is_flagged) {
      updateJob(id, {
        status: "quarantined",
        message: `Flagged (risk ${Number(scan.risk_score ?? 0).toFixed(2)})`,
      });
      onUploadSuccess?.({
        document_id: "",
        filename: file.name,
        status: "quarantined",
        message: "Document quarantined by security scan.",
        security_scan_passed: false,
      });
      return;
    }

    updateJob(id, { status: "uploading", progress: 0 });

    let upload: UploadResponse;
    try {
      upload = await apiClient.uploadDocument(
        file,
        (pct) => updateJob(id, { progress: pct }),
        signal
      );
    } catch (err) {
      if (isCancelled(err) || cancelAllRef.current) {
        updateJob(id, { status: "cancelled", message: "Cancelled." });
        return;
      }
      const { message, code } = classifyUploadError(err);
      updateJob(id, {
        status: "error",
        message,
        errorCode: code,
        progress: 0,
      });
      onUploadSuccess?.({
        document_id: "",
        filename: file.name,
        status: "failed",
        message,
        security_scan_passed: true,
      });
      return;
    }

    updateJob(id, { status: "processing", progress: 100 });
    await new Promise((r) => setTimeout(r, 200));

    const st = (upload.status || "").toLowerCase();
    if (st === "quarantined") {
      updateJob(id, {
        status: "quarantined",
        message: upload.message || "Quarantined after upload.",
        response: upload,
      });
      onUploadSuccess?.(upload);
      return;
    }
    if (st === "failed") {
      updateJob(id, {
        status: "error",
        message: upload.message || "Ingest failed on server.",
        errorCode: "INGEST_FAILED",
        response: upload,
      });
      onUploadSuccess?.(upload);
      return;
    }

    updateJob(id, {
      status: "success",
      message:
        upload.chunks_upserted != null
          ? `${upload.chunks_upserted} chunks · ${upload.status}`
          : upload.message || upload.status,
      response: upload,
      progress: 100,
    });
    onUploadSuccess?.(upload);
  };

  const runQueue = async () => {
    const pending = jobs.filter((j) => j.status === "queued");
    if (!pending.length || running) return;

    cancelAllRef.current = false;
    setRunning(true);
    setBanner(null);

    for (const job of pending) {
      if (cancelAllRef.current) break;

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await processOne(job, controller.signal);
      } catch (err) {
        if (!isCancelled(err)) {
          const { message, code } = classifyUploadError(err);
          updateJob(job.id, { status: "error", message, errorCode: code });
        }
      }
      abortRef.current = null;
    }

    setRunning(false);

    setJobs((prev) => {
      const ok = prev.filter((j) => j.status === "success").length;
      const q = prev.filter((j) => j.status === "quarantined").length;
      const bad = prev.filter((j) => j.status === "error").length;
      const cancelled = prev.filter((j) => j.status === "cancelled").length;

      if (!cancelAllRef.current) {
        const type =
          bad && !ok ? "error" : bad || q ? "warn" : "success";
        setBanner({
          type,
          message: `Finished: ${ok} uploaded, ${q} quarantined, ${bad} failed${
            cancelled ? `, ${cancelled} cancelled` : ""
          }.`,
        });
      }
      return prev;
    });
  };

  const queuedCount = jobs.filter((j) => j.status === "queued").length;
  const failedCount = jobs.filter((j) => j.status === "error").length;
  const activeCount = jobs.filter((j) =>
    ["scanning", "uploading", "processing"].includes(j.status)
  ).length;

  const overallPct =
    jobs.length === 0
      ? 0
      : Math.round(
          jobs.reduce((acc, j) => {
            if (
              ["success", "quarantined", "error", "cancelled"].includes(
                j.status
              )
            ) {
              return acc + 100;
            }
            return acc + j.progress;
          }, 0) / jobs.length
        );

  return (
    <div className="mx-auto max-w-2xl rounded-xl border border-gray-100 bg-white p-6 shadow-md">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold text-gray-800">
            Upload Documents
          </h2>
          <p className="mt-0.5 text-xs text-gray-400">
            Drag &amp; drop or browse · up to {MAX_BULK_FILES} files ·{" "}
            {formatBytes(MAX_UPLOAD_BYTES)} each
          </p>
        </div>
        {jobs.length > 0 && !running && (
          <button
            type="button"
            onClick={clearAll}
            className="text-xs font-medium text-gray-500 hover:text-gray-800"
          >
            Clear list
          </button>
        )}
      </div>

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (!running) inputRef.current?.click();
          }
        }}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDragOver={onDragOver}
        onDrop={onDrop}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-blue-500 bg-blue-50 ring-2 ring-blue-200"
            : "border-gray-300 bg-gray-50 hover:border-blue-500"
        } ${running ? "pointer-events-none opacity-60" : ""}`}
        aria-label="Drop files here or press Enter to browse"
      >
        <input
          ref={inputRef}
          type="file"
          id={inputId}
          className="hidden"
          multiple
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
          accept={ACCEPTED}
          disabled={running}
        />
        <label
          htmlFor={inputId}
          className="flex cursor-pointer flex-col items-center"
        >
          <Upload
            className={`mb-3 h-12 w-12 ${
              dragOver ? "text-blue-600" : "text-blue-500"
            }`}
          />
          <p className="text-sm font-medium text-gray-700">
            {dragOver ? (
              <span className="text-blue-700">
                Drop files to add them to the queue
              </span>
            ) : (
              <>
                Drag &amp; drop files here, or{" "}
                <span className="text-blue-600 underline">browse</span>
              </>
            )}
          </p>
          <p className="mt-1 flex items-center gap-1 text-xs text-gray-400">
            <Files className="h-3.5 w-3.5" />
            Multi-file · PDF · Office · text · images
          </p>
        </label>
      </div>

      {jobs.length > 0 && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-gray-500">
              {jobs.length} file{jobs.length === 1 ? "" : "s"} · {queuedCount}{" "}
              queued · {activeCount} active · {failedCount} failed
            </p>
            <div className="flex flex-wrap gap-2">
              {!running && failedCount > 0 && (
                <button
                  type="button"
                  onClick={retryFailed}
                  className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Retry failed ({failedCount})
                </button>
              )}
              {running ? (
                <button
                  type="button"
                  onClick={cancelAll}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100"
                >
                  <Square className="h-3.5 w-3.5 fill-current" />
                  Cancel all
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void runQueue()}
                  disabled={queuedCount === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  <Shield className="h-3.5 w-3.5" />
                  Scan &amp; upload
                  {queuedCount > 0 ? ` (${queuedCount})` : ""}
                </button>
              )}
            </div>
          </div>

          {running && (
            <div>
              <div className="mb-1 flex justify-between text-[11px] text-gray-500">
                <span>Overall progress</span>
                <span className="tabular-nums">{overallPct}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                <div
                  className="h-2 bg-blue-600 transition-all duration-300"
                  style={{ width: `${overallPct}%` }}
                />
              </div>
            </div>
          )}

          <ul className="max-h-80 space-y-2 overflow-y-auto">
            {jobs.map((job) => (
              <li
                key={job.id}
                className={`rounded-lg border px-3 py-2 ${
                  job.status === "error"
                    ? "border-rose-200 bg-rose-50/60"
                    : job.status === "quarantined"
                      ? "border-amber-200 bg-amber-50/50"
                      : "border-gray-100 bg-gray-50"
                }`}
              >
                <div className="flex items-center gap-3">
                  <FileTypeIcon name={job.file.name} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-gray-800">
                      {job.file.name}
                    </div>
                    <div className="text-[11px] text-gray-500">
                      {formatBytes(job.file.size)}
                      {fileExt(job.file.name)
                        ? ` · ${fileExt(job.file.name).toUpperCase()}`
                        : ""}
                      {" · "}
                      <StatusLabel status={job.status} />
                      {job.errorCode ? ` · ${job.errorCode}` : ""}
                    </div>
                    {job.message && (
                      <div
                        className={`mt-0.5 text-[11px] ${
                          job.status === "error"
                            ? "text-rose-700"
                            : "text-gray-500"
                        }`}
                      >
                        {job.message}
                      </div>
                    )}
                    {job.status === "uploading" && (
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-200">
                        <div
                          className="h-1.5 bg-blue-500 transition-all"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                    )}
                  </div>

                  {!running &&
                    (job.status === "queued" || job.status === "error") && (
                      <div className="flex shrink-0 items-center gap-1">
                        {job.status === "error" && (
                          <button
                            type="button"
                            title="Re-queue this file"
                            onClick={() =>
                              updateJob(job.id, {
                                status: "queued",
                                progress: 0,
                                message: undefined,
                                errorCode: undefined,
                              })
                            }
                            className="rounded-md p-1.5 text-amber-700 hover:bg-amber-100"
                            aria-label={`Retry ${job.file.name}`}
                          >
                            <RotateCcw className="h-4 w-4" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => removeJob(job.id)}
                          className="rounded-md p-1.5 text-gray-400 hover:bg-rose-50 hover:text-rose-600"
                          aria-label={`Remove ${job.file.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    )}

                  {job.status === "success" && (
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
                  )}
                  {job.status === "quarantined" && (
                    <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" />
                  )}
                  {job.status === "error" && (
                    <AlertCircle className="h-5 w-5 shrink-0 text-rose-500" />
                  )}
                  {["scanning", "uploading", "processing"].includes(
                    job.status
                  ) && (
                    <Loader2 className="h-5 w-5 shrink-0 animate-spin text-blue-500" />
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {banner && (
        <div
          role="status"
          className={`mt-4 flex items-start gap-2 rounded-lg p-3 text-sm ${
            banner.type === "success"
              ? "border border-green-100 bg-green-50 text-green-700"
              : banner.type === "warn"
                ? "border border-amber-100 bg-amber-50 text-amber-800"
                : banner.type === "info"
                  ? "border border-sky-100 bg-sky-50 text-sky-800"
                  : "border border-red-100 bg-red-50 text-red-700"
          }`}
        >
          <span className="flex-1">{banner.message}</span>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="opacity-50 hover:opacity-100"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}