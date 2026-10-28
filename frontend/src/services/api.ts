/**
 * Enterprise API client — production-ready fetch layer.
 * Path: frontend/src/components/services/api.ts
 *
 * Drop-in compatible with:
 *   import api from "./api"
 *   api("/analytics")
 *
 * Also exports:
 *   apiClient, ApiError, getApiErrorMessage, ApiResponse, ...
 */
const RAW_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ||
  "http://localhost:8000";

/** Normalize base: strip trailing slash. */
const API_BASE_URL = RAW_BASE.replace(/\/$/, "");

const ACCESS_KEY = "doc_intel_access_token";
const CSRF_KEY = "doc_intel_csrf";
const CSRF_COOKIE = "csrf_token";

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 2;
const RETRY_BASE_MS = 400;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
  code?: string;
}

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined | Array<string | number>
>;

export type ApiRequestOptions = {
  headers?: Record<string, string>;
  params?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  skipAuth?: boolean;
  noRetry?: boolean;
  noCoalesce?: boolean;
  /** Unwrap { success, data } envelopes automatically. */
  unwrap?: boolean;
  init?: Omit<RequestInit, "headers" | "body" | "signal" | "method">;
};

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;
  path?: string;

  constructor(
    message: string,
    opts?: {
      status?: number;
      code?: string;
      details?: unknown;
      path?: string;
    }
  ) {
    super(message);
    this.name = "ApiError";
    this.status = opts?.status ?? 0;
    this.code = opts?.code;
    this.details = opts?.details;
    this.path = opts?.path;
  }
}

export function getApiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof DOMException && err.name === "AbortError") {
    return "Request cancelled.";
  }
  if (err instanceof Error) {
    if (err.name === "AbortError") return "Request cancelled.";
    return err.message || "Request failed.";
  }
  return "Unexpected API error.";
}

// ---------------------------------------------------------------------------
// Token / CSRF
// ---------------------------------------------------------------------------

function readAccessToken(): string | null {
  try {
    return sessionStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

function readStoredCsrf(): string | null {
  try {
    return sessionStorage.getItem(CSRF_KEY);
  } catch {
    return null;
  }
}

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(
      `(?:^|; )${name.replace(/[$()*+.?[\\\]^{|}]/g, "\\$&")}=([^;]*)`
    )
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getCsrfToken(): string | null {
  return readStoredCsrf() || getCookie(CSRF_COOKIE);
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function buildUrl(endpoint: string, params?: QueryParams): string {
  let path: string;
  if (endpoint.startsWith("http")) {
    path = endpoint;
  } else if (endpoint.startsWith("/api")) {
    path = `${API_BASE_URL}${endpoint}`;
  } else if (endpoint.startsWith("/")) {
    path = `${API_BASE_URL}${endpoint}`;
  } else {
    path = `${API_BASE_URL}/${endpoint}`;
  }

  if (!params || Object.keys(params).length === 0) return path;

  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) usp.append(key, String(v));
    } else {
      usp.set(key, String(value));
    }
  }
  const qs = usp.toString();
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
}
// ---------------------------------------------------------------------------
// Retry / coalesce
// ---------------------------------------------------------------------------

const inflight = new Map<string, Promise<unknown>>();

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

function isRetryableStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

function jitteredDelay(attempt: number): number {
  const base = RETRY_BASE_MS * 2 ** attempt;
  return base + Math.floor(Math.random() * base * 0.4);
}

function mergeSignals(
  timeoutMs: number,
  outer?: AbortSignal
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const onOuter = () => controller.abort();
  if (outer) {
    if (outer.aborted) controller.abort();
    else outer.addEventListener("abort", onOuter, { once: true });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      outer?.removeEventListener("abort", onOuter);
    },
  };
}

// ---------------------------------------------------------------------------
// Core request
// ---------------------------------------------------------------------------

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const ct = response.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return undefined;
    }
  }
  const text = await response.text();
  return text.length ? text : undefined;
}

function extractErrorMessage(
  status: number,
  body: unknown,
  fallback: string
): { message: string; code?: string } {
  if (body && typeof body === "object") {
    const o = body as Record<string, unknown>;
    const message =
      (typeof o.detail === "string" && o.detail) ||
      (typeof o.message === "string" && o.message) ||
      (typeof o.error === "string" && o.error) ||
      fallback;
    const code = typeof o.code === "string" ? o.code : undefined;
    return { message, code };
  }
  if (typeof body === "string" && body.trim()) {
    return { message: body };
  }
  if (status === 401)
    return {
      message: "Session expired. Please sign in again.",
      code: "unauthorized",
    };
  if (status === 403)
    return {
      message: "You do not have permission to perform this action.",
      code: "forbidden",
    };
  if (status === 404)
    return { message: "Resource not found.", code: "not_found" };
  if (status === 429)
    return {
      message: "Too many requests. Try again shortly.",
      code: "rate_limited",
    };
  if (status >= 500)
    return {
      message: "Server error. Please try again.",
      code: "server_error",
    };
  return { message: fallback };
}

async function rawRequest<T>(
  method: string,
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const {
    headers: extraHeaders,
    params,
    body,
    signal: outerSignal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    skipAuth = false,
    noRetry = false,
    unwrap = false,
    init,
  } = options;

  const url = buildUrl(endpoint, params);
  const isGet =
    method.toUpperCase() === "GET" || method.toUpperCase() === "HEAD";

  const coalesceKey =
    isGet && !options.noCoalesce ? `${method}:${url}` : null;
  if (coalesceKey) {
    const existing = inflight.get(coalesceKey);
    if (existing) return existing as Promise<T>;
  }

  const run = (async (): Promise<T> => {
    const attempts = noRetry ? 0 : MAX_RETRIES;
    let lastErr: unknown;

    for (let attempt = 0; attempt <= attempts; attempt++) {
      const { signal, cleanup } = mergeSignals(timeoutMs, outerSignal);
      try {
        const headers: Record<string, string> = {
          Accept: "application/json",
          ...extraHeaders,
        };

        let requestBody: BodyInit | undefined;
        if (body !== undefined && body !== null && !isGet) {
          if (typeof FormData !== "undefined" && body instanceof FormData) {
            requestBody = body;
            delete headers["Content-Type"];
          } else if (typeof Blob !== "undefined" && body instanceof Blob) {
            requestBody = body;
          } else if (typeof body === "string") {
            requestBody = body;
            headers["Content-Type"] =
              headers["Content-Type"] || "application/json";
          } else {
            requestBody = JSON.stringify(body);
            headers["Content-Type"] =
              headers["Content-Type"] || "application/json";
          }
        }

        if (!skipAuth) {
          const token = readAccessToken();
          if (token) headers.Authorization = `Bearer ${token}`;
          if (!isGet) {
            const csrf = getCsrfToken();
            if (csrf) headers["X-CSRF-Token"] = csrf;
          }
        }

        const response = await fetch(url, {
          method,
          headers,
          body: requestBody,
          credentials: "include",
          signal,
          ...init,
        });

        const parsed = await parseBody(response);

        if (!response.ok) {
          const { message, code } = extractErrorMessage(
            response.status,
            parsed,
            `API Error: ${response.status}`
          );
          const err = new ApiError(message, {
            status: response.status,
            code,
            details: parsed,
            path: endpoint,
          });

          if (
            attempt < attempts &&
            isRetryableStatus(response.status) &&
            !outerSignal?.aborted
          ) {
            lastErr = err;
            cleanup();
            await sleep(jitteredDelay(attempt), outerSignal);
            continue;
          }
          throw err;
        }

        if (
          unwrap &&
          parsed &&
          typeof parsed === "object" &&
          "success" in (parsed as object) &&
          "data" in (parsed as object)
        ) {
          const env = parsed as ApiResponse<T>;
          if (env.success === false) {
            throw new ApiError(env.message || env.error || "Request failed.", {
              status: response.status,
              code: env.code,
              details: env,
              path: endpoint,
            });
          }
          return env.data;
        }

        return parsed as T;
      } catch (err) {
        cleanup();

        if (err instanceof ApiError) {
          if (
            attempt < attempts &&
            isRetryableStatus(err.status) &&
            !outerSignal?.aborted
          ) {
            lastErr = err;
            await sleep(jitteredDelay(attempt), outerSignal);
            continue;
          }
          throw err;
        }

        if (err instanceof DOMException && err.name === "AbortError") {
          throw new ApiError("Request cancelled or timed out.", {
            status: 0,
            code: "aborted",
            path: endpoint,
          });
        }

        if (attempt < attempts && !outerSignal?.aborted) {
          lastErr = err;
          await sleep(jitteredDelay(attempt), outerSignal);
          continue;
        }

        throw new ApiError(getApiErrorMessage(err), {
          status: 0,
          code: "network_error",
          path: endpoint,
        });
      }
    }

    throw lastErr instanceof ApiError
      ? lastErr
      : new ApiError(getApiErrorMessage(lastErr), {
          status: 0,
          path: endpoint,
        });
  })();

  if (coalesceKey) {
    inflight.set(coalesceKey, run);
    try {
      return await run;
    } finally {
      inflight.delete(coalesceKey);
    }
  }

  return run;
}
// ---------------------------------------------------------------------------
// Public: legacy `api()` + rich client
// ---------------------------------------------------------------------------

/**
 * Drop-in compatible with the original helper:
 *   api("/analytics")
 *   api("/items", { method: "POST", body: JSON.stringify(payload) })
 */
export async function api<T = unknown>(
  endpoint: string,
  options?: RequestInit & {
    params?: QueryParams;
    timeoutMs?: number;
    skipAuth?: boolean;
    noRetry?: boolean;
    unwrap?: boolean;
  }
): Promise<T> {
  const {
    params,
    timeoutMs,
    skipAuth,
    noRetry,
    unwrap,
    headers: initHeaders,
    body,
    signal,
    method = "GET",
    ...rest
  } = options || {};

  const headers: Record<string, string> = {};
  if (initHeaders) {
    new Headers(initHeaders as HeadersInit).forEach((v, k) => {
      headers[k] = v;
    });
  }

  let parsedBody: unknown = undefined;
  if (body !== undefined && body !== null) {
    if (typeof body === "string") {
      try {
        parsedBody = JSON.parse(body);
      } catch {
        parsedBody = body;
      }
    } else {
      parsedBody = body;
    }
  }

  return rawRequest<T>(String(method), endpoint, {
    headers,
    params,
    body: parsedBody,
    signal: (signal as AbortSignal | null) ?? undefined,
    timeoutMs,
    skipAuth,
    noRetry,
    unwrap,
    init: rest,
  });
}

export const apiClient = {
  getBaseUrl(): string {
    return API_BASE_URL;
  },

  getAccessToken: readAccessToken,
  getCsrfToken,

  async get<T = unknown>(
    endpoint: string,
    options?: ApiRequestOptions
  ): Promise<T> {
    return rawRequest<T>("GET", endpoint, options);
  },

  async post<T = unknown>(
    endpoint: string,
    body?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    return rawRequest<T>("POST", endpoint, { ...options, body });
  },

  async put<T = unknown>(
    endpoint: string,
    body?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    return rawRequest<T>("PUT", endpoint, { ...options, body });
  },

  async patch<T = unknown>(
    endpoint: string,
    body?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    return rawRequest<T>("PATCH", endpoint, { ...options, body });
  },

  async delete<T = unknown>(
    endpoint: string,
    options?: ApiRequestOptions
  ): Promise<T> {
    return rawRequest<T>("DELETE", endpoint, options);
  },

  async upload<T = unknown>(
    endpoint: string,
    fileOrForm: FormData | File | Blob,
    options?: ApiRequestOptions & { fieldName?: string; filename?: string }
  ): Promise<T> {
    let form: FormData;
    if (typeof FormData !== "undefined" && fileOrForm instanceof FormData) {
      form = fileOrForm;
    } else {
      form = new FormData();
      const field = options?.fieldName || "file";
      const blob = fileOrForm as Blob;
      const filename =
        options?.filename ||
        (typeof File !== "undefined" &&
          fileOrForm instanceof File &&
          fileOrForm.name) ||
        "upload.bin";
      form.append(field, blob, filename);
    }
    return rawRequest<T>("POST", endpoint, {
      ...options,
      body: form,
      timeoutMs: options?.timeoutMs ?? 120_000,
    });
  },

  async health(
    options?: ApiRequestOptions
  ): Promise<{ status: string; [key: string]: unknown }> {
    try {
      return await rawRequest("GET", "/health", {
        ...options,
        skipAuth: true,
        timeoutMs: options?.timeoutMs ?? 8_000,
      });
    } catch {
      return rawRequest("GET", "/api/v1/health", {
        ...options,
        skipAuth: true,
        timeoutMs: options?.timeoutMs ?? 8_000,
      });
    }
  },
};

export default api;