/**
 * Enterprise audit service — production-ready client.
 * Path: frontend/src/services/audit.ts
 *
 * Features:
 * - Typed audit log search, detail, export, and summary APIs
 * - Filters: actor, action, resource, severity, date range, free-text
 * - Pagination (page/cursor), AbortSignal, soft cache for summaries
 * - Retry + jitter, in-flight GET coalescing via shared api layer
 * - Browser export download helper
 * - Real-time WebSocket stream with auto-reconnect + heartbeat
 * - ApiError-friendly messages for UI toasts
 */
import {
  apiClient,
  ApiError,
  getApiErrorMessage,
  type ApiRequestOptions,
  type QueryParams,
} from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AuditSeverity = "info" | "low" | "medium" | "high" | "critical";

export type AuditAction =
  | "login"
  | "logout"
  | "login_failed"
  | "mfa_challenge"
  | "mfa_success"
  | "mfa_failed"
  | "password_reset"
  | "user.create"
  | "user.update"
  | "user.delete"
  | "role.assign"
  | "role.revoke"
  | "document.upload"
  | "document.delete"
  | "document.download"
  | "document.view"
  | "search"
  | "rag.query"
  | "export"
  | "settings.update"
  | "api.access"
  | string;

export interface AuditActor {
  id: string | number;
  username?: string;
  email?: string;
  display_name?: string;
  roles?: string[];
}

export interface AuditResource {
  type: string;
  id: string;
  name?: string;
}

export interface AuditEvent {
  id: string;
  ts: string;
  action: AuditAction;
  severity: AuditSeverity;
  actor?: AuditActor;
  resource?: AuditResource;
  ip?: string;
  user_agent?: string;
  request_id?: string;
  session_id?: string;
  message?: string;
  metadata?: Record<string, unknown>;
  success?: boolean;
}

export interface AuditListResponse {
  items: AuditEvent[];
  total?: number;
  page?: number;
  page_size?: number;
  next_cursor?: string;
  has_more?: boolean;
}

export interface AuditQuery {
  q?: string;
  actor_id?: string | number;
  action?: AuditAction | AuditAction[];
  resource_type?: string;
  resource_id?: string;
  severity?: AuditSeverity | AuditSeverity[];
  success?: boolean;
  from?: string;
  to?: string;
  window?: "1h" | "24h" | "7d" | "30d" | "90d";
  page?: number;
  page_size?: number;
  cursor?: string;
  sort?: "ts_desc" | "ts_asc" | "severity_desc";
}

export interface AuditSummary {
  total_events: number;
  failed_auth_count: number;
  by_action: Array<{ key: string; count: number; pct?: number }>;
  by_severity: Array<{ key: AuditSeverity; count: number; pct?: number }>;
  by_actor: Array<{ key: string; label?: string; count: number }>;
  period: { from: string; to: string };
  generated_at?: string;
}

export type AuditExportFormat = "csv" | "json" | "xlsx";

export interface AuditExportRequest extends AuditQuery {
  format?: AuditExportFormat;
}

export interface AuditExportResult {
  download_url?: string;
  job_id?: string;
  status: "ready" | "processing" | "failed";
  expires_at?: string;
  filename?: string;
}

export type AuditRequestOptions = Pick<
  ApiRequestOptions,
  "signal" | "timeoutMs" | "noRetry" | "skipAuth"
>;

// ---------------------------------------------------------------------------
// WebSocket types
// ---------------------------------------------------------------------------

export type AuditSocketStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "error";

export type AuditStreamFilter = {
  actions?: AuditAction[];
  severities?: AuditSeverity[];
  actor_id?: string | number;
  resource_type?: string;
};

export type AuditStreamHandlers = {
  onEvent?: (event: AuditEvent) => void;
  onStatus?: (status: AuditSocketStatus) => void;
  onError?: (err: Error) => void;
  /** Server heartbeat / ping payload */
  onPing?: () => void;
};

export type AuditStreamOptions = AuditStreamFilter &
  AuditStreamHandlers & {
    /** Override WS path (default /api/v1/audit/ws). */
    path?: string;
    /** Max reconnect attempts (default Infinity). */
    maxRetries?: number;
    /** Base reconnect delay ms (default 1000). */
    reconnectBaseMs?: number;
    /** Max reconnect delay ms (default 30000). */
    reconnectMaxMs?: number;
    /** Client ping interval ms; 0 disables (default 25000). */
    heartbeatMs?: number;
  };

export type AuditStreamSubscription = {
  /** Current connection status. */
  getStatus: () => AuditSocketStatus;
  /** Update server-side filters without full reconnect when possible. */
  updateFilters: (filters: AuditStreamFilter) => void;
  /** Force reconnect. */
  reconnect: () => void;
  /** Close and stop auto-reconnect. */
  close: () => void;
};

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function toParams(query?: AuditQuery): QueryParams {
  if (!query) return {};
  const p: QueryParams = {};
  if (query.q) p.q = query.q;
  if (query.actor_id != null) p.actor_id = query.actor_id;
  if (query.action != null) {
    p.action = Array.isArray(query.action)
      ? query.action.join(",")
      : query.action;
  }
  if (query.resource_type) p.resource_type = query.resource_type;
  if (query.resource_id) p.resource_id = query.resource_id;
  if (query.severity != null) {
    p.severity = Array.isArray(query.severity)
      ? query.severity.join(",")
      : query.severity;
  }
  if (query.success != null) p.success = query.success;
  if (query.from) p.from = query.from;
  if (query.to) p.to = query.to;
  if (query.window) p.window = query.window;
  if (query.page != null) p.page = query.page;
  if (query.page_size != null) p.page_size = query.page_size;
  if (query.cursor) p.cursor = query.cursor;
  if (query.sort) p.sort = query.sort;
  return p;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(
        new ApiError("Request cancelled.", { status: 0, code: "cancelled" })
      );
      return;
    }
    const t = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(
        new ApiError("Request cancelled.", { status: 0, code: "cancelled" })
      );
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

type CacheEntry = { expires: number; data: unknown };
const summaryCache = new Map<string, CacheEntry>();
const SUMMARY_TTL_MS = 20_000;

function cacheGet<T>(key: string): T | undefined {
  const hit = summaryCache.get(key);
  if (!hit) return undefined;
  if (Date.now() > hit.expires) {
    summaryCache.delete(key);
    return undefined;
  }
  return hit.data as T;
}

function cacheSet(key: string, data: unknown, ttl = SUMMARY_TTL_MS): void {
  summaryCache.set(key, { data, expires: Date.now() + ttl });
}

export function clearAuditCache(): void {
  summaryCache.clear();
}

export { getApiErrorMessage, ApiError };

// ---------------------------------------------------------------------------
// WebSocket stream implementation
// ---------------------------------------------------------------------------

function httpToWsBase(httpBase: string): string {
  if (httpBase.startsWith("https://")) {
    return "wss://" + httpBase.slice("https://".length);
  }
  if (httpBase.startsWith("http://")) {
    return "ws://" + httpBase.slice("http://".length);
  }
  if (typeof window !== "undefined" && window.location?.protocol === "https:") {
    return `wss://${window.location.host}`;
  }
  return `ws://${httpBase.replace(/^[a-z]+:\/\//, "")}`;
}

function buildWsUrl(path: string, filters?: AuditStreamFilter): string {
  const base = httpToWsBase(apiClient.getBaseUrl());
  const url = new URL(
    path.startsWith("/") ? path : `/${path}`,
    base.endsWith("/") ? base : base + "/"
  );
  // Prefer token in query for WS (headers not always available)
  const token = apiClient.getAccessToken();
  if (token) url.searchParams.set("access_token", token);
  if (filters?.actions?.length) {
    url.searchParams.set("actions", filters.actions.join(","));
  }
  if (filters?.severities?.length) {
    url.searchParams.set("severities", filters.severities.join(","));
  }
  if (filters?.actor_id != null) {
    url.searchParams.set("actor_id", String(filters.actor_id));
  }
  if (filters?.resource_type) {
    url.searchParams.set("resource_type", filters.resource_type);
  }
  return url.toString();
}

function isAuditEvent(payload: unknown): payload is AuditEvent {
  if (!payload || typeof payload !== "object") return false;
  const o = payload as Record<string, unknown>;
  return typeof o.id === "string" && typeof o.ts === "string" && "action" in o;
}

function createAuditStream(options: AuditStreamOptions = {}): AuditStreamSubscription {
  if (typeof WebSocket === "undefined") {
    throw new ApiError("WebSocket is not available in this environment.");
  }

  const path = options.path ?? "/api/v1/audit/ws";
  const maxRetries = options.maxRetries ?? Number.POSITIVE_INFINITY;
  const reconnectBaseMs = options.reconnectBaseMs ?? 1_000;
  const reconnectMaxMs = options.reconnectMaxMs ?? 30_000;
  const heartbeatMs = options.heartbeatMs ?? 25_000;

  let filters: AuditStreamFilter = {
    actions: options.actions,
    severities: options.severities,
    actor_id: options.actor_id,
    resource_type: options.resource_type,
  };

  let ws: WebSocket | null = null;
  let status: AuditSocketStatus = "idle";
  let closedByUser = false;
  let retryCount = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  const setStatus = (next: AuditSocketStatus) => {
    status = next;
    options.onStatus?.(next);
  };

  const clearHeartbeat = () => {
    if (heartbeatTimer != null) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  };

  const clearReconnect = () => {
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const startHeartbeat = () => {
    clearHeartbeat();
    if (heartbeatMs <= 0) return;
    heartbeatTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: "ping", ts: Date.now() }));
        } catch {
          /* ignore */
        }
      }
    }, heartbeatMs);
  };

  const scheduleReconnect = () => {
    if (closedByUser) return;
    if (retryCount >= maxRetries) {
      setStatus("error");
      options.onError?.(
        new ApiError("Audit WebSocket: max reconnect attempts reached.", {
          code: "ws_max_retries",
        })
      );
      return;
    }
    const exp = Math.min(
      reconnectMaxMs,
      reconnectBaseMs * 2 ** Math.min(retryCount, 8)
    );
    const jitter = Math.floor(Math.random() * exp * 0.3);
    const delay = exp + jitter;
    retryCount += 1;
    setStatus("reconnecting");
    clearReconnect();
    reconnectTimer = setTimeout(() => connect(), delay);
  };

  const handleMessage = (raw: MessageEvent) => {
    let data: unknown = raw.data;
    if (typeof data === "string") {
      try {
        data = JSON.parse(data);
      } catch {
        return;
      }
    }
    if (!data || typeof data !== "object") return;
    const msg = data as Record<string, unknown>;

    // Envelope forms: { type, payload } or bare AuditEvent
    const type = typeof msg.type === "string" ? msg.type : undefined;

    if (type === "ping" || type === "pong" || type === "heartbeat") {
      options.onPing?.();
      if (type === "ping" && ws?.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: "pong", ts: Date.now() }));
        } catch {
          /* ignore */
        }
      }
      return;
    }

    if (type === "error") {
      const message =
        (typeof msg.message === "string" && msg.message) ||
        "Audit stream error";
      options.onError?.(new ApiError(message, { code: "ws_server_error" }));
      return;
    }

    const payload =
      type === "audit.event" || type === "event"
        ? msg.payload ?? msg.data ?? msg.event
        : msg;

    if (isAuditEvent(payload)) {
      // Client-side filter safety net
      if (
        filters.severities?.length &&
        !filters.severities.includes(payload.severity)
      ) {
        return;
      }
      if (
        filters.actions?.length &&
        !filters.actions.includes(payload.action)
      ) {
        return;
      }
      options.onEvent?.(payload);
      // Invalidate summary cache on live activity
      summaryCache.clear();
      return;
    }
  };

  const connect = () => {
    clearReconnect();
    clearHeartbeat();

    if (ws) {
      try {
        ws.onopen = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
      } catch {
        /* ignore */
      }
      ws = null;
    }

    setStatus(retryCount > 0 ? "reconnecting" : "connecting");

    let url: string;
    try {
      url = buildWsUrl(path, filters);
    } catch (err) {
      setStatus("error");
      options.onError?.(
        err instanceof Error
          ? err
          : new ApiError("Failed to build WebSocket URL.")
      );
      scheduleReconnect();
      return;
    }

    try {
      ws = new WebSocket(url);
    } catch (err) {
      setStatus("error");
      options.onError?.(
        err instanceof Error
          ? err
          : new ApiError("Failed to open audit WebSocket.")
      );
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      retryCount = 0;
      setStatus("open");
      startHeartbeat();
      // Subscribe message for backends that configure filters post-connect
      try {
        ws?.send(
          JSON.stringify({
            type: "subscribe",
            filters: {
              actions: filters.actions,
              severities: filters.severities,
              actor_id: filters.actor_id,
              resource_type: filters.resource_type,
            },
          })
        );
      } catch {
        /* ignore */
      }
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      options.onError?.(
        new ApiError("Audit WebSocket error.", { code: "ws_error" })
      );
    };

    ws.onclose = () => {
      clearHeartbeat();
      ws = null;
      if (closedByUser) {
        setStatus("closed");
        return;
      }
      scheduleReconnect();
    };
  };

  // Kick off
  closedByUser = false;
  connect();

  return {
    getStatus: () => status,
    updateFilters: (next) => {
      filters = { ...filters, ...next };
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(
            JSON.stringify({
              type: "subscribe",
              filters: {
                actions: filters.actions,
                severities: filters.severities,
                actor_id: filters.actor_id,
                resource_type: filters.resource_type,
              },
            })
          );
          return;
        } catch {
          /* fall through to reconnect */
        }
      }
      retryCount = 0;
      connect();
    },
    reconnect: () => {
      closedByUser = false;
      retryCount = 0;
      connect();
    },
    close: () => {
      closedByUser = true;
      clearReconnect();
      clearHeartbeat();
      if (ws) {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        ws = null;
      }
      setStatus("closed");
    },
  };
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

const AuditService = {
  /**
   * Search / list audit events.
   * GET /api/v1/audit/events
   */
  async list(
    query?: AuditQuery,
    options?: AuditRequestOptions
  ): Promise<AuditListResponse> {
    return apiClient.get<AuditListResponse>("/api/v1/audit/events", {
      params: toParams(query),
      signal: options?.signal,
      timeoutMs: options?.timeoutMs,
      noRetry: options?.noRetry,
      skipAuth: options?.skipAuth,
    });
  },

  /**
   * Single event by id.
   * GET /api/v1/audit/events/:id
   */
  async getById(
    id: string,
    options?: AuditRequestOptions
  ): Promise<AuditEvent> {
    return apiClient.get<AuditEvent>(
      `/api/v1/audit/events/${encodeURIComponent(id)}`,
      {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs,
        noRetry: options?.noRetry,
        skipAuth: options?.skipAuth,
      }
    );
  },

  /**
   * Aggregated summary for dashboards.
   * GET /api/v1/audit/summary
   */
  async getSummary(
    query?: Pick<AuditQuery, "from" | "to" | "window" | "actor_id" | "action">,
    options?: AuditRequestOptions & { skipCache?: boolean }
  ): Promise<AuditSummary> {
    const params = toParams(query as AuditQuery);
    const key = `summary:${JSON.stringify(params)}`;
    if (!options?.skipCache) {
      const cached = cacheGet<AuditSummary>(key);
      if (cached) return cached;
    }
    const data = await apiClient.get<AuditSummary>("/api/v1/audit/summary", {
      params,
      signal: options?.signal,
      timeoutMs: options?.timeoutMs,
      noRetry: options?.noRetry,
      skipAuth: options?.skipAuth,
    });
    if (!options?.skipCache) cacheSet(key, data);
    return data;
  },

  /**
   * Recent high-severity or failed-auth stream for live panels.
   */
  async getRecentAlerts(
    limit = 20,
    options?: AuditRequestOptions
  ): Promise<AuditListResponse> {
    return this.list(
      {
        severity: ["high", "critical"],
        page_size: limit,
        sort: "ts_desc",
        window: "24h",
      },
      options
    );
  },

  /**
   * Failed authentication attempts.
   */
  async getFailedLogins(
    query?: Pick<
      AuditQuery,
      "from" | "to" | "window" | "page" | "page_size" | "cursor"
    >,
    options?: AuditRequestOptions
  ): Promise<AuditListResponse> {
    return this.list(
      {
        ...query,
        action: ["login_failed", "mfa_failed"],
        sort: "ts_desc",
      },
      options
    );
  },

  /**
   * Activity for a specific actor (user).
   */
  async getActorActivity(
    actorId: string | number,
    query?: Omit<AuditQuery, "actor_id">,
    options?: AuditRequestOptions
  ): Promise<AuditListResponse> {
    return this.list({ ...query, actor_id: actorId }, options);
  },

  /**
   * Activity for a resource (document, setting, etc.).
   */
  async getResourceActivity(
    resourceType: string,
    resourceId: string,
    query?: Omit<AuditQuery, "resource_type" | "resource_id">,
    options?: AuditRequestOptions
  ): Promise<AuditListResponse> {
    return this.list(
      { ...query, resource_type: resourceType, resource_id: resourceId },
      options
    );
  },

  /**
   * Request export of filtered audit log.
   * POST /api/v1/audit/export
   */
  async export(
    request: AuditExportRequest = {},
    options?: AuditRequestOptions
  ): Promise<AuditExportResult> {
    const { format = "csv", ...filters } = request;
    return apiClient.post<AuditExportResult>(
      "/api/v1/audit/export",
      { format, ...filters },
      {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs ?? 60_000,
        noRetry: options?.noRetry,
        skipAuth: options?.skipAuth,
      }
    );
  },

  /**
   * Poll export job.
   * GET /api/v1/audit/export/:jobId
   */
  async getExportStatus(
    jobId: string,
    options?: AuditRequestOptions
  ): Promise<AuditExportResult> {
    return apiClient.get<AuditExportResult>(
      `/api/v1/audit/export/${encodeURIComponent(jobId)}`,
      {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs,
        noRetry: options?.noRetry,
        skipAuth: options?.skipAuth,
      }
    );
  },

  /**
   * Download export in the browser (polls processing jobs up to ~60s).
   */
  async downloadExport(
    resultOrJob: AuditExportResult | string,
    options?: AuditRequestOptions & { filename?: string; pollMs?: number }
  ): Promise<void> {
    if (typeof window === "undefined" || typeof document === "undefined") {
      throw new ApiError("downloadExport requires a browser environment.");
    }

    let result: AuditExportResult =
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
      throw new ApiError("Audit export failed.", { code: "export_failed" });
    }
    if (result.status === "processing") {
      throw new ApiError("Audit export timed out.", {
        code: "export_timeout",
      });
    }

    const filename =
      options?.filename ||
      result.filename ||
      `audit-export-${new Date().toISOString().slice(0, 10)}.csv`;

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
      const a = document.createElement("a");
      a.href = result.download_url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      return;
    }

    if (result.job_id) {
      const token = apiClient.getAccessToken();
      const base = apiClient.getBaseUrl();
      const res = await fetch(
        `${base}/api/v1/audit/export/${encodeURIComponent(result.job_id)}/file`,
        {
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: options?.signal,
        }
      );
      if (!res.ok) {
        throw new ApiError(`Failed to download audit export (${res.status}).`, {
          status: res.status,
        });
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      try {
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } finally {
        URL.revokeObjectURL(blobUrl);
      }
      return;
    }

    throw new ApiError("Export result has no download_url or job_id.");
  },

  /**
   * Subscribe to real-time audit events over WebSocket.
   */
  subscribe(options?: AuditStreamOptions): AuditStreamSubscription {
    return createAuditStream(options ?? {});
  },

  clearCache: clearAuditCache,
};

export default AuditService;