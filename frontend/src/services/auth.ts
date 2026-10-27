import apiClient from "../lib/apiClient";

/* ============================================================
 * TYPES
 * ============================================================
 */

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  authenticated: boolean;
  user?: AuthUser;
  message?: string;
}

export interface RefreshResponse {
  authenticated: boolean;
  expires_in?: number;
}

export interface AuthUser {
  id: string;
  username: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  roles?: string[];
  permissions?: string[];
  is_active?: boolean;
}

export interface SessionInfo {
  authenticated: boolean;
  user?: AuthUser;
  expires_at?: string;
}

export interface HealthResponse {
  status: string;
  authenticated?: boolean;
}

/* ============================================================
 * ERRORS
 * ============================================================
 */

export class AuthenticationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthenticationError";
  }
}

export class AuthorizationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthorizationError";
  }
}

/* ============================================================
 * CSRF
 * ============================================================
 */

function getCookie(
  name: string
): string | null {
  const match = document.cookie.match(
    new RegExp(
      `(^| )${name}=([^;]+)`
    )
  );

  return match
    ? decodeURIComponent(match[2])
    : null;
}

export function getCsrfToken(): string | null {
  return getCookie("csrf_token");
}

/* ============================================================
 * AUTH SERVICE
 * ============================================================
 */

class AuthService {
  /**
   * Login
   * Backend should return:
   * - access token cookie
   * - refresh token cookie
   * - csrf cookie
   */
  async login(
    username: string,
    password: string
  ): Promise<LoginResponse> {
    const response =
      await apiClient.post<LoginResponse>(
        "/api/v1/auth/login",
        {
          username,
          password,
        },
        {
          withCredentials: true,
        }
      );

    return response;
  }

  /**
   * Refresh access token
   */
  async refresh(): Promise<RefreshResponse> {
    const response =
      await apiClient.post<RefreshResponse>(
        "/api/v1/auth/refresh",
        {},
        {
          withCredentials: true,
        }
      );

    return response;
  }

  /**
   * Logout
   * Clears server cookies
   */
  async logout(): Promise<void> {
    await apiClient.post(
      "/api/v1/auth/logout",
      {},
      {
        withCredentials: true,
      }
    );
  }

  /**
   * Current user
   */
  async me(): Promise<AuthUser> {
    const response =
      await apiClient.get<AuthUser>(
        "/api/v1/auth/me",
        {
          withCredentials: true,
        }
      );

    return response;
  }

  /**
   * Validate session
   */
  async validateSession(): Promise<SessionInfo> {
    const response =
      await apiClient.get<SessionInfo>(
        "/api/v1/auth/session",
        {
          withCredentials: true,
        }
      );

    return response;
  }

  /**
   * Health endpoint
   */
  async health(): Promise<HealthResponse> {
    const response =
      await apiClient.get<HealthResponse>(
        "/health"
      );

    return response;
  }

  /**
   * Is authenticated
   */
  async isAuthenticated(): Promise<boolean> {
    try {
      const session =
        await this.validateSession();

      return session.authenticated;
    } catch {
      return false;
    }
  }

  /**
   * Has role
   */
  async hasRole(
    role: string
  ): Promise<boolean> {
    try {
      const user =
        await this.me();

      return (
        user.roles?.includes(role) ??
        false
      );
    } catch {
      return false;
    }
  }

  /**
   * Has permission
   */
  async hasPermission(
    permission: string
  ): Promise<boolean> {
    try {
      const user =
        await this.me();

      return (
        user.permissions?.includes(
          permission
        ) ?? false
      );
    } catch {
      return false;
    }
  }
}

const authService = new AuthService();

export default authService;