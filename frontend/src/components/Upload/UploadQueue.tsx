import React, {
  useMemo,
  useState,
  useCallback,
} from "react";

import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Filter,
  Loader2,
  Play,
  RefreshCw,
  Trash2,
  Upload,
  XCircle,
  FileText,
  Database,
  Brain,
} from "lucide-react";

export type QueueStatus =
  | "queued"
  | "uploading"
  | "processing"
  | "extracting"
  | "chunking"
  | "embedding"
  | "indexing"
  | "completed"
  | "failed"
  | "cancelled";

export type QueuePriority =
  | "low"
  | "normal"
  | "high"
  | "critical";

export interface UploadQueueItem {
  id: string;
  uploadId?: string;

  name: string;
  size: number;

  progress: number;

  status: QueueStatus;

  priority: QueuePriority;

  uploadedBy?: string;

  createdAt?: string;

  startedAt?: string;

  completedAt?: string;

  retries?: number;

  error?: string;
}

interface UploadQueueProps {
  items: UploadQueueItem[];

  onStart?: (
    fileId: string
  ) => Promise<void>;

  onRetry?: (
    fileId: string
  ) => Promise<void>;

  onCancel?: (
    fileId: string
  ) => Promise<void>;

  onRemove?: (
    fileId: string
  ) => void;

  onRetryAll?: () => Promise<void>;

  onRemoveCompleted?: () => void;
}

const formatFileSize = (
  bytes: number
): string => {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(
      bytes / 1024
    ).toFixed(2)} KB`;
  }

  if (bytes < 1024 * 1024 * 1024) {
    return `${(
      bytes /
      (1024 * 1024)
    ).toFixed(2)} MB`;
  }

  return `${(
    bytes /
    (1024 * 1024 * 1024)
  ).toFixed(2)} GB`;
};

const MetricCard: React.FC<{
  label: string;
  value: number;
  color: string;
}> = ({
  label,
  value,
  color,
}) => (
  <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
    <p className="text-xs uppercase tracking-wide text-slate-500">
      {label}
    </p>

    <p
      className={`mt-2 text-2xl font-bold ${color}`}
    >
      {value}
    </p>
  </div>
);

const UploadQueue: React.FC<
  UploadQueueProps
> = ({
  items,
  onStart,
  onRetry,
  onCancel,
  onRemove,
  onRetryAll,
  onRemoveCompleted,
}) => {
  const [filter, setFilter] =
    useState("all");

  const [apiError, setApiError] =
    useState<string | null>(null);

  const [busyItems, setBusyItems] =
    useState<Set<string>>(new Set());

  const statistics = useMemo(
    () => ({
      total: items.length,

      queued: items.filter(
        (i) =>
          i.status === "queued"
      ).length,

      uploading: items.filter(
        (i) =>
          i.status ===
          "uploading"
      ).length,

      processing: items.filter(
        (i) =>
          [
            "processing",
            "extracting",
            "chunking",
            "embedding",
            "indexing",
          ].includes(i.status)
      ).length,

      completed: items.filter(
        (i) =>
          i.status ===
          "completed"
      ).length,

      failed: items.filter(
        (i) =>
          i.status === "failed"
      ).length,
    }),
    [items]
  );

  const filteredItems =
    useMemo(() => {
      if (filter === "all")
        return items;

      return items.filter(
        (item) =>
          item.status === filter
      );
    }, [items, filter]);

  const executeAction =
    useCallback(
      async (
        itemId: string,
        action: () => Promise<void>
      ) => {
        try {
          setApiError(null);

          setBusyItems(
            (previous) =>
              new Set([
                ...previous,
                itemId,
              ])
          );

          await action();
        } catch (error) {
          console.error(error);

          setApiError(
            "Unable to communicate with upload service."
          );
        } finally {
          setBusyItems(
            (previous) => {
              const next =
                new Set(previous);

              next.delete(itemId);

              return next;
            }
          );
        }
      },
      []
    );

  const handleRetry =
    async (
      item: UploadQueueItem
    ) => {
      await executeAction(
        item.id,
        async () => {
          await onRetry?.(
            item.id
          );
        }
      );
    };

  const handleCancel =
    async (
      item: UploadQueueItem
    ) => {
      await executeAction(
        item.id,
        async () => {
          await onCancel?.(
            item.id
          );
        }
      );
    };

  const getPriorityColor = (
    priority: QueuePriority
  ) => {
    switch (priority) {
      case "critical":
        return "bg-red-500/10 text-red-400";

      case "high":
        return "bg-amber-500/10 text-amber-400";

      case "normal":
        return "bg-blue-500/10 text-blue-400";

      default:
        return "bg-slate-500/10 text-slate-400";
    }
  };

  const getStageIcon = (
    status: QueueStatus
  ) => {
    switch (status) {
      case "extracting":
        return (
          <FileText className="h-4 w-4 text-cyan-400" />
        );

      case "chunking":
        return (
          <Database className="h-4 w-4 text-purple-400" />
        );

      case "embedding":
        return (
          <Brain className="h-4 w-4 text-indigo-400" />
        );

      case "indexing":
        return (
          <Loader2 className="h-4 w-4 animate-spin text-amber-400" />
        );

      case "completed":
        return (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        );

      case "failed":
        return (
          <AlertTriangle className="h-4 w-4 text-red-400" />
        );

      case "cancelled":
        return (
          <XCircle className="h-4 w-4 text-slate-500" />
        );

      case "uploading":
        return (
          <Upload className="h-4 w-4 text-blue-400" />
        );

      default:
        return (
          <Clock3 className="h-4 w-4 text-slate-400" />
        );
    }
  };

  if (!items.length) {
    return (
      <div
        role="status"
        className="rounded-xl border border-slate-800 bg-slate-900 p-8 text-center"
      >
        <Upload className="mx-auto mb-4 h-10 w-10 text-slate-500" />

        <h3 className="text-lg font-semibold text-white">
          No Uploads Queued
        </h3>

        <p className="mt-2 text-slate-400">
          Add documents to begin
          ingestion and indexing.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {apiError && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-xl border border-red-900 bg-red-950/30 p-4 text-red-400"
        >
          {apiError}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard
          label="Total"
          value={statistics.total}
          color="text-white"
        />

        <MetricCard
          label="Queued"
          value={statistics.queued}
          color="text-slate-300"
        />

        <MetricCard
          label="Uploading"
          value={
            statistics.uploading
          }
          color="text-blue-400"
        />

        <MetricCard
          label="Processing"
          value={
            statistics.processing
          }
          color="text-purple-400"
        />

        <MetricCard
          label="Completed"
          value={
            statistics.completed
          }
          color="text-emerald-400"
        />

        <MetricCard
          label="Failed"
          value={
            statistics.failed
          }
          color="text-red-400"
        />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900">
        <div className="flex flex-col gap-4 border-b border-slate-800 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">
              Upload Queue
            </h3>

            <p className="text-sm text-slate-400">
              Monitor document ingestion,
              extraction, chunking, embedding,
              and indexing.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                onRetryAll?.()
              }
              aria-label="Retry all failed uploads"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white hover:bg-slate-700"
            >
              Retry Failed
            </button>

            <button
              type="button"
              onClick={
                onRemoveCompleted
              }
              aria-label="Remove completed uploads"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white hover:bg-slate-700"
            >
              Clear Completed
            </button>
          </div>
        </div>

        <div className="border-b border-slate-800 p-4">
          <select
            value={filter}
            onChange={(e) =>
              setFilter(
                e.target.value
              )
            }
            aria-label="Filter uploads"
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-white"
          >
            <option value="all">
              All
            </option>
            <option value="queued">
              Queued
            </option>
            <option value="uploading">
              Uploading
            </option>
            <option value="processing">
              Processing
            </option>
            <option value="completed">
              Completed
            </option>
            <option value="failed">
              Failed
            </option>
          </select>
        </div>

        <div className="divide-y divide-slate-800">
          {filteredItems.map(
            (item) => {
              const isBusy =
                busyItems.has(
                  item.id
                );

              return (
                <div
                  key={item.id}
                  role="article"
                  tabIndex={0}
                  aria-label={`Upload ${item.name}`}
                  className="p-5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex-1">
                      <div className="mb-2 flex items-center gap-3">
                        {getStageIcon(
                          item.status
                        )}

                        <h4 className="font-medium text-white">
                          {item.name}
                        </h4>

                        <span
                          className={`rounded-full px-2 py-1 text-xs font-medium ${getPriorityColor(
                            item.priority
                          )}`}
                        >
                          {
                            item.priority
                          }
                        </span>
                      </div>

                      <p className="mb-3 text-sm text-slate-400">
                        {formatFileSize(
                          item.size
                        )}
                      </p>

                      <div
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={
                          item.progress
                        }
                        className="h-2 overflow-hidden rounded-full bg-slate-800"
                      >
                        <div
                          className="h-full bg-indigo-500 transition-all"
                          style={{
                            width: `${item.progress}%`,
                          }}
                        />
                      </div>

                      <p className="mt-2 text-xs text-slate-500">
                        {
                          item.progress
                        }
                        %
                      </p>

                      {item.error && (
                        <div className="mt-3 rounded-lg border border-red-900 bg-red-950/30 p-3 text-sm text-red-400">
                          {
                            item.error
                          }
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {item.status ===
                        "queued" && (
                        <button
                          type="button"
                          disabled={
                            isBusy
                          }
                          aria-label={`Start ${item.name}`}
                          onClick={() =>
                            onStart?.(
                              item.id
                            )
                          }
                          className="rounded-lg bg-indigo-600 px-3 py-2 text-white hover:bg-indigo-500 disabled:opacity-50"
                        >
                          <Play className="h-4 w-4" />
                        </button>
                      )}

                      {item.status ===
                        "failed" && (
                        <button
                          type="button"
                          disabled={
                            isBusy
                          }
                          aria-label={`Retry ${item.name}`}
                          onClick={() =>
                            handleRetry(
                              item
                            )
                          }
                          className="rounded-lg bg-amber-600 px-3 py-2 text-white hover:bg-amber-500 disabled:opacity-50"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </button>
                      )}

                      {[
                        "queued",
                        "uploading",
                        "processing",
                        "extracting",
                        "chunking",
                        "embedding",
                        "indexing",
                      ].includes(
                        item.status
                      ) && (
                        <button
                          type="button"
                          disabled={
                            isBusy
                          }
                          aria-label={`Cancel ${item.name}`}
                          onClick={() =>
                            handleCancel(
                              item
                            )
                          }
                          className="rounded-lg bg-red-600 px-3 py-2 text-white hover:bg-red-500 disabled:opacity-50"
                        >
                          <XCircle className="h-4 w-4" />
                        </button>
                      )}

                      <button
                        type="button"
                        aria-label={`Remove ${item.name}`}
                        onClick={() =>
                          onRemove?.(
                            item.id
                          )
                        }
                        className="rounded-lg bg-slate-700 px-3 py-2 text-white hover:bg-slate-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            }
          )}
        </div>
      </div>
    </div>
  );
};

export default UploadQueue;