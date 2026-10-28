/**
 * Enterprise auth service — cookie + bearer hybrid session.
 * Drop into: frontend/src/services/auth.ts
 *
 * Compatible with LoginForm:
 *   login, verifyMfa, register, requestPasswordReset, me, health, getBaseUrl
 *
 * Design:
 * - Prefer HttpOnly cookie sessions (VITE_AUTH_COOKIES=true).
 * - Optional in-memory access token + sessionStorage dual-write.
 * - Single-flight refresh, CSRF header injection, 401 → refresh retry.
 * - Roles / permissions helpers for route guards.
 */
import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = (
  (import.meta.env.VITE_API_URL as string | undefined) ||
  "http://localhost:8000"
).replace(/\/$/, "");

/** Persist access token across reloads (sessionStorage only — not localStorage). */
const PERSIST_ACCESS =
  (import.meta.env.VITE_AUTH_PERSIST_ACCESS as string | undefined) !== "false";

const ACCESS_KEY = "doc_intel_access_token";
const CSRF_KEY = "doc_intel_csrf";
const CSRF_COOKIE = "csrf_token";

/** When true, rely on HttpOnly cookies; still attach bearer if present. */
const USE_COOKIES =
  (import.meta.env.VITE_AUTH_COOKIES as string | undefined) === "true";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuthUser {
  id: string | number;
  username: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  roles?: string[];
  permissions?: string[];
  is_active?: boolean;
  mfa_enabled?: boolean;
  [key: string]: unknown;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  authenticated?: boolean;
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  refresh_token?: string;
  csrf_token?: string;
  user?: AuthUser;
  message?: string;
  /** When true, client must complete MFA before session is active. */
  mfa_required?: boolean;
  mfa_token?: string;
  methods?: Array<"totp" | "recovery">;
}

export interface RefreshResponse {
  authenticated?: boolean;
  access_token?: string;
  expires_in?: number;
  csrf_token?: string;
  user?: AuthUser;
}

export interface SessionInfo {
  authenticated: boolean;
  user?: AuthUser;
  expires_at?: string;
}

export interface HealthResponse {
  status: string;
  authenticated?: boolean;
  [key: string]: unknown;
}

export type MeResponse = AuthUser;

export interface RegisterRequest {
  email: string;
  password: string;
  username?: string;
  first_name?: string;
  last_name?: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  password: string;
}

export interface MfaVerifyRequest {
  mfa_token: string;
  code: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class AuthenticationError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "AuthenticationError";
    this.status = status;
  }
}

export class AuthorizationError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "AuthorizationError";
    this.status = status;
  }
}

// ---------------------------------------------------------------------------
// Cookie / CSRF helpers
// ---------------------------------------------------------------------------

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/[$()*+.?[\\\]^{|}]/g, "\\$&")}=([^;]*)`)
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getCsrfToken(): string | null {
  return csrfToken || getCookie(CSRF_COOKIE) || readStoredCsrf();
}

function readStoredCsrf(): string | null {
  try {
    return sessionStorage.getItem(CSRF_KEY);
  } catch {
    return null;
  }
}

function writeStoredCsrf(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(CSRF_KEY, token);
    else sessionStorage.removeItem(CSRF_KEY);
  } catch {
    /* private mode */
  }
}
// ---------------------------------------------------------------------------
// In-memory session
// ---------------------------------------------------------------------------

let accessToken: string | null = null;
let csrfToken: string | null = null;
let currentUser: AuthUser | null = null;
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
let refreshPromise: Promise<string | null> | null = null;

function readStoredAccess(): string | null {
  if (!PERSIST_ACCESS) return null;
  try {
    return sessionStorage.getItem(ACCESS_KEY);
  } catch {
    return null;
  }
}

function writeStoredAccess(token: string | null): void {
  if (!PERSIST_ACCESS) return;
  try {
    if (token) sessionStorage.setItem(ACCESS_KEY, token);
    else sessionStorage.removeItem(ACCESS_KEY);
  } catch {
    /* private mode */
  }
}

// Hydrate from sessionStorage on module load
accessToken = readStoredAccess();
csrfToken = readStoredCsrf();

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

const http: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  withCredentials: true,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = accessToken || readStoredAccess();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  const csrf = getCsrfToken();
  if (
    csrf &&
    config.method &&
    !["get", "head", "options"].includes(config.method.toLowerCase())
  ) {
    config.headers = config.headers ?? {};
    config.headers["X-CSRF-Token"] = csrf;
  }
  return config;
});

http.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    const status = error.response?.status;

    if (
      status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes("/auth/login") &&
      !original.url?.includes("/auth/refresh") &&
      !original.url?.includes("/auth/register") &&
      !original.url?.includes("/auth/forgot-password")
    ) {
      original._retry = true;
      const newToken = await authService.refresh();
      if (newToken) {
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${newToken}`;
        return http.request(original);
      }
      unauthorizedHandler?.();
    }

    if (status === 403) {
      const detail =
        (error.response?.data as { detail?: string } | undefined)?.detail ||
        "Forbidden";
      return Promise.reject(new AuthorizationError(detail, 403));
    }

    return Promise.reject(error);
  }
);
// ---------------------------------------------------------------------------
// Auth service
// ---------------------------------------------------------------------------

const authService = {
  getBaseUrl(): string {
    return API_BASE;
  },

  getAccessToken(): string | null {
    return accessToken || readStoredAccess();
  },

  getUser(): AuthUser | null {
    return currentUser;
  },

  isLoggedIn(): boolean {
    return Boolean(accessToken || readStoredAccess() || USE_COOKIES);
  },

  onUnauthorized(handler: UnauthorizedHandler): void {
    unauthorizedHandler = handler;
  },

  setSession(
    token: string | null,
    user: AuthUser | null = null,
    csrf: string | null = null
  ): void {
    accessToken = token;
    writeStoredAccess(token);
    if (user) currentUser = user;
    if (csrf) {
      csrfToken = csrf;
      writeStoredCsrf(csrf);
    }
  },

  clearSession(): void {
    accessToken = null;
    csrfToken = null;
    currentUser = null;
    writeStoredAccess(null);
    writeStoredCsrf(null);
  },

  /**
   * Login
   * POST /api/v1/auth/login  { username, password }
   */
  async login(
    username: string,
    password: string,
    signal?: AbortSignal
  ): Promise<LoginResponse> {
    const { data } = await http.post<LoginResponse>(
      "/api/v1/auth/login",
      { username, password } satisfies LoginRequest,
      { signal }
    );

    if (data?.mfa_required && data.mfa_token) {
      return data;
    }

    if (data?.access_token) {
      this.setSession(
        data.access_token,
        data.user ?? null,
        data.csrf_token ?? getCsrfToken()
      );
    } else if (data?.user) {
      currentUser = data.user;
      if (data.csrf_token) {
        csrfToken = data.csrf_token;
        writeStoredCsrf(data.csrf_token);
      }
    } else if (data?.csrf_token) {
      csrfToken = data.csrf_token;
      writeStoredCsrf(data.csrf_token);
    }

    return data;
  },

  /**
   * Complete MFA after password login.
   * POST /api/v1/auth/mfa/verify  { mfa_token, code }
   */
  async verifyMfa(
    mfaToken: string,
    code: string,
    signal?: AbortSignal
  ): Promise<LoginResponse> {
    const { data } = await http.post<LoginResponse>(
      "/api/v1/auth/mfa/verify",
      { mfa_token: mfaToken, code } satisfies MfaVerifyRequest,
      { signal }
    );

    if (data?.access_token) {
      this.setSession(
        data.access_token,
        data.user ?? null,
        data.csrf_token ?? getCsrfToken()
      );
    } else if (data?.user) {
      currentUser = data.user;
      if (data.csrf_token) {
        csrfToken = data.csrf_token;
        writeStoredCsrf(data.csrf_token);
      }
    } else if (!data?.authenticated && !USE_COOKIES) {
      throw new AuthenticationError("Malformed MFA response: missing session.");
    }

    return data;
  },

  /**
   * Register a new account.
   * POST /api/v1/auth/register
   */
  async register(
    email: string,
    password: string,
    signal?: AbortSignal,
    extra?: Partial<RegisterRequest>
  ): Promise<unknown> {
    const body: RegisterRequest = {
      email,
      password,
      ...extra,
    };
    const { data } = await http.post("/api/v1/auth/register", body, { signal });
    return data;
  },

  /**
   * Request password reset email.
   * POST /api/v1/auth/forgot-password  { email }
   */
  async requestPasswordReset(
    email: string,
    signal?: AbortSignal
  ): Promise<unknown> {
    const { data } = await http.post(
      "/api/v1/auth/forgot-password",
      { email } satisfies ForgotPasswordRequest,
      { signal }
    );
    return data;
  },

  /**
   * Complete password reset with token from email.
   * POST /api/v1/auth/reset-password  { token, password }
   */
  async resetPassword(
    token: string,
    password: string,
    signal?: AbortSignal
  ): Promise<unknown> {
    const { data } = await http.post(
      "/api/v1/auth/reset-password",
      { token, password } satisfies ResetPasswordRequest,
      { signal }
    );
    return data;
  },

  /**
   * Current user profile.
   * GET /api/v1/auth/me
   */
  async me(signal?: AbortSignal): Promise<MeResponse> {
    const { data } = await http.get<MeResponse>("/api/v1/auth/me", { signal });
    currentUser = data;
    return data;
  },

  /**
   * Validate session (lightweight).
   * GET /api/v1/auth/session
   */
  async validateSession(signal?: AbortSignal): Promise<SessionInfo> {
    try {
      const { data } = await http.get<SessionInfo>("/api/v1/auth/session", {
        signal,
      });
      if (data?.user) currentUser = data.user;
      return data;
    } catch (err) {
      const status = (err as AxiosError)?.response?.status;
      if (status === 401) {
        return { authenticated: false };
      }
      throw err;
    }
  },
    /**
   * Refresh access token (cookie refresh or body).
   * Single-flight: concurrent callers share one promise.
   */
  async refresh(): Promise<string | null> {
    if (refreshPromise) return refreshPromise;

    refreshPromise = (async () => {
      try {
        const { data } = await http.post<RefreshResponse>(
          "/api/v1/auth/refresh",
          {}
        );
        if (data?.access_token) {
          this.setSession(
            data.access_token,
            data.user ?? currentUser,
            data.csrf_token ?? csrfToken
          );
          return data.access_token;
        }
        if (data?.authenticated && data.user) {
          currentUser = data.user;
          if (data.csrf_token) {
            csrfToken = data.csrf_token;
            writeStoredCsrf(data.csrf_token);
          }
          return accessToken;
        }
        if (data?.authenticated) {
          return accessToken;
        }
        this.clearSession();
        return null;
      } catch {
        this.clearSession();
        return null;
      } finally {
        refreshPromise = null;
      }
    })();

    return refreshPromise;
  },

  /**
   * Logout — clears server cookies and local session.
   */
  async logout(): Promise<void> {
    try {
      await http.post("/api/v1/auth/logout", {});
    } catch {
      /* best-effort */
    } finally {
      this.clearSession();
    }
  },

  /**
   * API health.
   * GET /health  (or /api/v1/health fallback)
   */
  async health(signal?: AbortSignal): Promise<HealthResponse> {
    try {
      const { data } = await http.get<HealthResponse>("/health", { signal });
      return data;
    } catch {
      const { data } = await http.get<HealthResponse>("/api/v1/health", {
        signal,
      });
      return data;
    }
  },

  /**
   * Is authenticated (network check).
   */
  async isAuthenticated(): Promise<boolean> {
    try {
      const session = await this.validateSession();
      return Boolean(session.authenticated);
    } catch {
      try {
        await this.me();
        return true;
      } catch {
        return false;
      }
    }
  },

  /**
   * Has role (uses cached user, fetches me() if needed).
   */
  async hasRole(role: string): Promise<boolean> {
    try {
      const user = currentUser ?? (await this.me());
      return user.roles?.includes(role) ?? false;
    } catch {
      return false;
    }
  },

  /**
   * Has permission (uses cached user, fetches me() if needed).
   */
  async hasPermission(permission: string): Promise<boolean> {
    try {
      const user = currentUser ?? (await this.me());
      return user.permissions?.includes(permission) ?? false;
    } catch {
      return false;
    }
  },

  /**
   * Has any of the given roles.
   */
  async hasAnyRole(...roles: string[]): Promise<boolean> {
    try {
      const user = currentUser ?? (await this.me());
      return roles.some((r) => user.roles?.includes(r));
    } catch {
      return false;
    }
  },

  /**
   * Has all of the given permissions.
   */
  async hasAllPermissions(...permissions: string[]): Promise<boolean> {
    try {
      const user = currentUser ?? (await this.me());
      return permissions.every((p) => user.permissions?.includes(p));
    } catch {
      return false;
    }
  },
};

export default authService;