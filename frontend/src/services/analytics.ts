/**
 * Enterprise analytics service — production-ready client.
 * Drop into: frontend/src/services/analytics.ts
 *
 * Features:
 * - Typed overview, trends, usage, search, RAG, cost, and export APIs
 * - Date-range / granularity filters, pagination, AbortSignal
 * - Bearer + cookie credentials (aligned with auth service)
 * - Soft in-memory cache with TTL for expensive overview queries
 * - In-flight request coalescing + retry with jitter on 502/503/504
 * - Period compare (current vs previous) for KPI deltas
 * - Export download helper for browser save
 * - Friendly error mapping for UI toasts
 */
import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
} from "axios";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = (
  (import.meta.env.VITE_API_URL as string | undefined) ||
  "http://localhost:8000"
).replace(/\/$/, "");

const ACCESS_KEY = "doc_intel_access_token";
const DEFAULT_CACHE_TTL_MS = 30_000;
const MAX_RETRIES = 2;
const RETRY_BASE_MS = 400;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TimeGranularity = "hour" | "day" | "week" | "month";

export type AnalyticsDateRange = {
  /** ISO-8601 inclusive start */
  from?: string;
  /** ISO-8601 inclusive end */
  to?: string;
  /** Relative window, e.g. 7d, 30d, 90d, 12m */
  window?: "24h" | "7d" | "30d" | "90d" | "12m" | "ytd";
  granularity?: TimeGranularity;
};

export type PaginationParams = {
  page?: number;
  page_size?: number;
  cursor?: string;
};

export type AnalyticsOverview = {
  total_documents: number;
  total_chunks: number;
  total_queries: number;
  active_users_24h: number;
  ingestion_success_rate: number;
  avg_query_latency_ms: number;
  storage_bytes: number;
  period?: { from: string; to: string };
  generated_at?: string;
};

/** KPI with current value, previous period, and relative change. */
export type MetricDelta = {
  current: number;
  previous: number;
  /** (current - previous) / |previous| ; null if previous is 0 */
  change_ratio: number | null;
  change_abs: number;
};

export type AnalyticsOverviewCompare = {
  current: AnalyticsOverview;
  previous: AnalyticsOverview;
  deltas: {
    total_documents: MetricDelta;
    total_chunks: MetricDelta;
    total_queries: MetricDelta;
    active_users_24h: MetricDelta;
    ingestion_success_rate: MetricDelta;
    avg_query_latency_ms: MetricDelta;
    storage_bytes: MetricDelta;
  };
  period: { from: string; to: string };
  previous_period: { from: string; to: string };
};

export type TrendPoint = {
  ts: string;
  value: number;
  label?: string;
};

export type TrendSeries = {
  metric: string;
  unit?: string;
  points: TrendPoint[];
};

export type AnalyticsTrends = {
  series: TrendSeries[];
  granularity: TimeGranularity;
  period: { from: string; to: string };
};

export type UsageBreakdownItem = {
  key: string;
  label?: string;
  count: number;
  bytes?: number;
  cost_usd?: number;
  pct?: number;
};

export type AnalyticsUsage = {
  by_user: UsageBreakdownItem[];
  by_department?: UsageBreakdownItem[];
  by_document_type?: UsageBreakdownItem[];
  by_endpoint?: UsageBreakdownItem[];
  totals: {
    requests: number;
    documents: number;
    storage_bytes: number;
    cost_usd?: number;
  };
  period: { from: string; to: string };
};

export type SearchAnalytics = {
  total_searches: number;
  zero_result_rate: number;
  avg_latency_ms: number;
  top_queries: Array<{ query: string; count: number; avg_hits?: number }>;
  top_documents: Array<{
    document_id: string;
    title?: string;
    hits: number;
  }>;
  period: { from: string; to: string };
};

export type RagAnalytics = {
  total_conversations: number;
  total_messages: number;
  avg_tokens_in: number;
  avg_tokens_out: number;
  grounded_answer_rate?: number;
  citation_rate?: number;
  model_breakdown?: UsageBreakdownItem[];
  period: { from: string; to: string };
};

export type CostAnalytics = {
  currency: string;
  total_usd: number;
  by_service: UsageBreakdownItem[];
  by_day?: TrendPoint[];
  period: { from: string; to: string };
};

export type DocumentActivity = {
  document_id: string;
  title?: string;
  views: number;
  downloads: number;
  queries: number;
  last_accessed_at?: string;
};

export type AuditAnalyticsSummary = {
  total_events: number;
  by_action: UsageBreakdownItem[];
  by_actor: UsageBreakdownItem[];
  failed_auth_count: number;
  period: { from: string; to: string };
};

export type ExportFormat = "csv" | "json" | "xlsx";

export type AnalyticsExportRequest = {
  report: "overview" | "usage" | "trends" | "search" | "rag" | "cost" | "audit";
  format?: ExportFormat;
} & AnalyticsDateRange;

export type AnalyticsExportResult = {
  download_url?: string;
  job_id?: string;
  status: "ready" | "processing" | "failed";
  expires_at?: string;
  filename?: string;
};

export type RequestOptions = {
  signal?: AbortSignal;
  /** Skip soft cache (default false for overview-style reads). */
  skipCache?: boolean;
  /** Override cache TTL ms. */
  cacheTtlMs?: number;
  /** Disable retry (default: retry on 502/503/504). */
  noRetry?: boolean;
};
// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class AnalyticsError extends Error {
  status?: number;
  code?: string;
  details?: unknown;

  constructor(
    message: string,
    opts?: { status?: number; code?: string; details?: unknown }
  ) {
    super(message);
    this.name = "AnalyticsError";
    this.status = opts?.status;
    this.code = opts?.code;
    this.details = opts?.details;
  }
}

export function getAnalyticsErrorMessage(err: unknown): string {
  if (err instanceof AnalyticsError) return err.message;
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as
      | { detail?: string; message?: string; error?: string }
      | string
      | undefined;
    if (typeof data === "string" && data.trim()) return data;
    if (data && typeof data === "object") {
      return (
        data.detail ||
        data.message ||
        data.error ||
        err.message ||
        "Analytics request failed."
      );
    }
    if (err.code === "ERR_CANCELED" || err.name === "CanceledError") {
      return "Request cancelled.";
    }
    if (!err.response) {
      return "Unable to reach analytics service. Check network connectivity.";
    }
    if (err.response.status === 401)
      return "Session expired. Please sign in again.";
    if (err.response.status === 403)
      return "You do not have permission to view analytics.";
    if (err.response.status === 429)
      return "Too many analytics requests. Try again shortly.";
    if (err.response.status >= 500)
      return "Analytics service is temporarily unavailable.";
    return err.message || "Analytics request failed.";
  }
  if (err instanceof Error) return err.message;
  return "Unexpected analytics error.";
}

// ---------------------------------------------------------------------------
// HTTP client (aligned with auth: bearer + cookies)
// ---------------------------------------------------------------------------

function readAccessToken(): string | null {
  try {
    return sessionStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

const http: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 45_000,
  withCredentials: true,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

http.interceptors.request.use((config) => {
  const token = readAccessToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// Soft cache (in-memory, tab-scoped)
// ---------------------------------------------------------------------------

type CacheEntry = { expires: number; data: unknown };
const cache = new Map<string, CacheEntry>();

function cacheKey(path: string, params?: Record<string, unknown>): string {
  return `${path}?${JSON.stringify(params ?? {})}`;
}

function getCached<T>(key: string): T | undefined {
  const hit = cache.get(key);
  if (!hit) return undefined;
  if (Date.now() > hit.expires) {
    cache.delete(key);
    return undefined;
  }
  return hit.data as T;
}

function setCache(key: string, data: unknown, ttlMs: number): void {
  cache.set(key, { data, expires: Date.now() + ttlMs });
}

export function clearAnalyticsCache(): void {
  cache.clear();
}

// ---------------------------------------------------------------------------
// In-flight coalescing (dedupe concurrent identical GETs)
// ---------------------------------------------------------------------------

const inflight = new Map<string, Promise<unknown>>();

// ---------------------------------------------------------------------------
// Retry helpers
// ---------------------------------------------------------------------------

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new AnalyticsError("Request cancelled.", { code: "cancelled" }));
      return;
    }
    const t = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new AnalyticsError("Request cancelled.", { code: "cancelled" }));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function isRetryable(err: unknown): boolean {
  if (!axios.isAxiosError(err)) return false;
  if (err.code === "ERR_CANCELED" || err.name === "CanceledError") return false;
  const status = err.response?.status;
  if (status == null) return true; // network error
  return status === 502 || status === 503 || status === 504;
}

function jitteredDelay(attempt: number): number {
  const base = RETRY_BASE_MS * 2 ** attempt;
  return base + Math.floor(Math.random() * base * 0.4);
}
// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function toQuery(
  range?: AnalyticsDateRange,
  extra?: Record<string, unknown>
): Record<string, unknown> {
  const q: Record<string, unknown> = { ...extra };
  if (range?.from) q.from = range.from;
  if (range?.to) q.to = range.to;
  if (range?.window) q.window = range.window;
  if (range?.granularity) q.granularity = range.granularity;
  return q;
}

function metricDelta(current: number, previous: number): MetricDelta {
  const change_abs = current - previous;
  const change_ratio =
    previous === 0
      ? current === 0
        ? 0
        : null
      : change_abs / Math.abs(previous);
  return { current, previous, change_ratio, change_abs };
}

async function getJson<T>(
  path: string,
  params?: Record<string, unknown>,
  options?: RequestOptions
): Promise<T> {
  const key = cacheKey(path, params);
  const ttl = options?.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;

  if (!options?.skipCache && ttl > 0) {
    const cached = getCached<T>(key);
    if (cached !== undefined) return cached;
  }

  const existing = inflight.get(key);
  if (existing) return existing as Promise<T>;

  const run = (async () => {
    let lastErr: unknown;
    const attempts = options?.noRetry ? 0 : MAX_RETRIES;

    for (let attempt = 0; attempt <= attempts; attempt++) {
      try {
        const config: AxiosRequestConfig = {
          params,
          signal: options?.signal,
        };
        const { data } = await http.get<T>(path, config);
        if (!options?.skipCache && ttl > 0) setCache(key, data, ttl);
        return data;
      } catch (err) {
        lastErr = err;
        if (
          attempt < attempts &&
          isRetryable(err) &&
          !options?.signal?.aborted
        ) {
          await sleep(jitteredDelay(attempt), options?.signal);
          continue;
        }
        throw mapError(err);
      }
    }
    throw mapError(lastErr);
  })();

  inflight.set(key, run);
  try {
    return await run;
  } finally {
    inflight.delete(key);
  }
}

async function postJson<T>(
  path: string,
  body: unknown,
  options?: RequestOptions
): Promise<T> {
  let lastErr: unknown;
  const attempts = options?.noRetry ? 0 : MAX_RETRIES;

  for (let attempt = 0; attempt <= attempts; attempt++) {
    try {
      const { data } = await http.post<T>(path, body, {
        signal: options?.signal,
      });
      return data;
    } catch (err) {
      lastErr = err;
      if (
        attempt < attempts &&
        isRetryable(err) &&
        !options?.signal?.aborted
      ) {
        await sleep(jitteredDelay(attempt), options?.signal);
        continue;
      }
      throw mapError(err);
    }
  }
  throw mapError(lastErr);
}

function mapError(err: unknown): AnalyticsError {
  if (err instanceof AnalyticsError) return err;
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError;
    if (ax.code === "ERR_CANCELED" || ax.name === "CanceledError") {
      return new AnalyticsError("Request cancelled.", {
        status: 0,
        code: "cancelled",
      });
    }
    const status = ax.response?.status;
    const payload = ax.response?.data as
      | { detail?: string; message?: string; code?: string }
      | undefined;
    return new AnalyticsError(getAnalyticsErrorMessage(err), {
      status,
      code: payload?.code,
      details: payload,
    });
  }
  return new AnalyticsError(getAnalyticsErrorMessage(err));
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

const AnalyticsService = {
  getBaseUrl(): string {
    return API_BASE;
  },

  clearCache: clearAnalyticsCache,

  async getOverview(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<AnalyticsOverview> {
    return getJson<AnalyticsOverview>(
      "/api/v1/analytics/overview",
      toQuery(range),
      options
    );
  },

  async getOverviewCompare(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<AnalyticsOverviewCompare> {
    try {
      return await getJson<AnalyticsOverviewCompare>(
        "/api/v1/analytics/overview/compare",
        toQuery(range),
        options
      );
    } catch (err) {
      if (!(err instanceof AnalyticsError) || err.status !== 404) throw err;

      const current = await this.getOverview(range, options);
      const previous = await getJson<AnalyticsOverview>(
        "/api/v1/analytics/overview",
        toQuery(range, { period: "previous" }),
        { ...options, skipCache: true }
      );

      return {
        current,
        previous,
        deltas: {
          total_documents: metricDelta(
            current.total_documents,
            previous.total_documents
          ),
          total_chunks: metricDelta(
            current.total_chunks,
            previous.total_chunks
          ),
          total_queries: metricDelta(
            current.total_queries,
            previous.total_queries
          ),
          active_users_24h: metricDelta(
            current.active_users_24h,
            previous.active_users_24h
          ),
          ingestion_success_rate: metricDelta(
            current.ingestion_success_rate,
            previous.ingestion_success_rate
          ),
          avg_query_latency_ms: metricDelta(
            current.avg_query_latency_ms,
            previous.avg_query_latency_ms
          ),
          storage_bytes: metricDelta(
            current.storage_bytes,
            previous.storage_bytes
          ),
        },
        period: current.period ?? { from: "", to: "" },
        previous_period: previous.period ?? { from: "", to: "" },
      };
    }
  },

  async getTrends(
    range?: AnalyticsDateRange,
    metrics?: string[],
    options?: RequestOptions
  ): Promise<AnalyticsTrends> {
    return getJson<AnalyticsTrends>(
      "/api/v1/analytics/trends",
      toQuery(
        range,
        metrics?.length ? { metrics: metrics.join(",") } : undefined
      ),
      { cacheTtlMs: 15_000, ...options }
    );
  },

  async getUsage(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<AnalyticsUsage> {
    return getJson<AnalyticsUsage>(
      "/api/v1/analytics/usage",
      toQuery(range),
      options
    );
  },

  async getSearchAnalytics(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<SearchAnalytics> {
    return getJson<SearchAnalytics>(
      "/api/v1/analytics/search",
      toQuery(range),
      options
    );
  },

  async getRagAnalytics(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<RagAnalytics> {
    return getJson<RagAnalytics>(
      "/api/v1/analytics/rag",
      toQuery(range),
      options
    );
  },

  async getCostAnalytics(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<CostAnalytics> {
    return getJson<CostAnalytics>(
      "/api/v1/analytics/cost",
      toQuery(range),
      { skipCache: true, ...options }
    );
  },
    async getDocumentActivity(
    range?: AnalyticsDateRange,
    pagination?: PaginationParams,
    options?: RequestOptions
  ): Promise<{
    items: DocumentActivity[];
    next_cursor?: string;
    total?: number;
  }> {
    return getJson(
      "/api/v1/analytics/documents",
      toQuery(range, {
        page: pagination?.page,
        page_size: pagination?.page_size,
        cursor: pagination?.cursor,
      }),
      options
    );
  },

  async getAuditSummary(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<AuditAnalyticsSummary> {
    return getJson<AuditAnalyticsSummary>(
      "/api/v1/analytics/audit",
      toQuery(range),
      { skipCache: true, ...options }
    );
  },

  async exportReport(
    request: AnalyticsExportRequest,
    options?: RequestOptions
  ): Promise<AnalyticsExportResult> {
    return postJson<AnalyticsExportResult>(
      "/api/v1/analytics/export",
      {
        report: request.report,
        format: request.format ?? "csv",
        from: request.from,
        to: request.to,
        window: request.window,
        granularity: request.granularity,
      },
      options
    );
  },

  async getExportStatus(
    jobId: string,
    options?: RequestOptions
  ): Promise<AnalyticsExportResult> {
    return getJson<AnalyticsExportResult>(
      `/api/v1/analytics/export/${encodeURIComponent(jobId)}`,
      undefined,
      { skipCache: true, ...options }
    );
  },

  /**
   * Download an export result in the browser.
   * Polls processing jobs (max ~60s), then triggers save via URL or blob.
   */
  async downloadExport(
    resultOrJob: AnalyticsExportResult | string,
    options?: RequestOptions & { filename?: string; pollMs?: number }
  ): Promise<void> {
    if (typeof window === "undefined" || typeof document === "undefined") {
      throw new AnalyticsError(
        "downloadExport requires a browser environment."
      );
    }

    let result: AnalyticsExportResult =
      typeof resultOrJob === "string"
        ? { job_id: resultOrJob, status: "processing" }
        : resultOrJob;

    const pollMs = options?.pollMs ?? 1500;
    const deadline = Date.now() + 60_000;

    while (
      result.status === "processing" &&
      result.job_id &&
      Date.now() < deadline
    ) {
      await sleep(pollMs, options?.signal);
      result = await this.getExportStatus(result.job_id, options);
    }

    if (result.status === "failed") {
      throw new AnalyticsError("Export job failed.", { code: "export_failed" });
    }
    if (result.status === "processing") {
      throw new AnalyticsError("Export job timed out.", {
        code: "export_timeout",
      });
    }

    const filename =
      options?.filename ||
      result.filename ||
      `analytics-export-${new Date().toISOString().slice(0, 10)}.csv`;

    let blobUrl: string;
    let revoke = false;

    if (result.download_url) {
      if (
        result.download_url.startsWith("http") &&
        !result.download_url.startsWith(window.location.origin)
      ) {
        const a = document.createElement("a");
        a.href = result.download_url;
        a.download = filename;
        a.rel = "noopener";
        a.target = "_blank";
        document.body.appendChild(a);
        a.click();
        a.remove();
        return;
      }
      blobUrl = result.download_url;
    } else if (result.job_id) {
      const token = readAccessToken();
      const res = await fetch(
        `${API_BASE}/api/v1/analytics/export/${encodeURIComponent(
          result.job_id
        )}/file`,
        {
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: options?.signal,
        }
      );
      if (!res.ok) {
        throw new AnalyticsError(
          `Failed to download export (${res.status}).`,
          { status: res.status }
        );
      }
      const blob = await res.blob();
      blobUrl = URL.createObjectURL(blob);
      revoke = true;
    } else {
      throw new AnalyticsError(
        "Export result has no download_url or job_id."
      );
    }

    try {
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      if (revoke) URL.revokeObjectURL(blobUrl);
    }
  },

  async getDashboardBundle(
    range?: AnalyticsDateRange,
    options?: RequestOptions
  ): Promise<{
    overview: AnalyticsOverview;
    trends: AnalyticsTrends;
    usage: AnalyticsUsage;
  }> {
    const [overview, trends, usage] = await Promise.all([
      this.getOverview(range, options),
      this.getTrends(range, undefined, options),
      this.getUsage(range, options),
    ]);
    return { overview, trends, usage };
  },
};

export default AnalyticsService;