 import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  ShieldCheck,
  Loader2,
  Eye,
  EyeOff,
  LogIn,
  AlertCircle,
  Wifi,
  WifiOff,
  Lock,
} from "lucide-react";

import authService from "../services/auth";

export interface LoginFormProps {
  onLoginSuccess?: () => void;
}

function getFriendlyError(
  error: unknown
): string {
  const err = error as {
    code?: string;
    message?: string;
    response?: {
      status?: number;
      data?: {
        detail?: string;
      };
    };
  };

  if (
    err?.code === "ERR_NETWORK"
  ) {
    return "Unable to reach authentication service.";
  }

  const status =
    err?.response?.status;

  switch (status) {
    case 400:
      return "Invalid request.";

    case 401:
      return "Invalid username or password.";

    case 403:
      return "Access denied.";

    case 429:
      return "Too many login attempts. Please wait.";

    case 500:
      return "Authentication service unavailable.";

    default:
      return (
        err?.response?.data
          ?.detail ||
        err?.message ||
        "Login failed."
      );
  }
}

export default function LoginForm({
  onLoginSuccess,
}: LoginFormProps) {
  const [
    username,
    setUsername,
  ] = useState("");

  const [
    password,
    setPassword,
  ] = useState("");

  const [
    loading,
    setLoading,
  ] = useState(false);

  const [
    error,
    setError,
  ] = useState<
    string | null
  >(null);

  const [
    showPassword,
    setShowPassword,
  ] = useState(false);

  const [
    apiHealthy,
    setApiHealthy,
  ] = useState<
    boolean | null
  >(null);

  const [
    loginAttempts,
    setLoginAttempts,
  ] = useState(0);

  const [
    capsLock,
    setCapsLock,
  ] = useState(false);

  const usernameRef =
    useRef<HTMLInputElement>(
      null
    );

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  useEffect(() => {
    let mounted = true;

    const checkHealth =
      async () => {
        try {
          await authService.health();

          if (mounted) {
            setApiHealthy(true);
          }
        } catch {
          if (mounted) {
            setApiHealthy(false);
          }
        }
      };

    void checkHealth();

    return () => {
      mounted = false;
    };
  }, []);

  const handleLogin =
    useCallback(
      async (
        e: React.FormEvent
      ) => {
        e.preventDefault();

        if (loading) {
          return;
        }

        setError(null);

        if (
          !username.trim()
        ) {
          setError(
            "Username is required."
          );

          return;
        }

        if (!password) {
          setError(
            "Password is required."
          );

          return;
        }

        setLoading(true);

        try {
          await authService.login(
            username.trim(),
            password
          );

          await authService.me();

          onLoginSuccess?.();
        } catch (err) {
          setLoginAttempts(
            (current) =>
              current + 1
          );

          setError(
            getFriendlyError(
              err
            )
          );
        } finally {
          setLoading(false);
        }
      },
      [
        username,
        password,
        loading,
        onLoginSuccess,
      ]
    );

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-500/30">
            <ShieldCheck className="h-8 w-8" />
          </div>

          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            Doc Intelligence
          </h1>

          <p className="mt-2 text-sm text-slate-500">
            Secure access to document
            ingestion, search, governance,
            and AI intelligence services.
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xl shadow-slate-200/60">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              {apiHealthy ? (
                <>
                  <Wifi className="h-4 w-4 text-emerald-500" />
                  <span className="text-emerald-600">
                    API Online
                  </span>
                </>
              ) : (
                <>
                  <WifiOff className="h-4 w-4 text-red-500" />
                  <span className="text-red-600">
                    API Offline
                  </span>
                </>
              )}
            </div>

            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Lock className="h-3 w-3" />
              Secure Session
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-800"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {loginAttempts >=
            3 && (
            <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900">
              Multiple failed sign-in
              attempts detected.
            </div>
          )}

          <form
            onSubmit={(e) =>
              void handleLogin(e)
            }
            className="space-y-4"
          >
            <div>
              <label
                htmlFor="username"
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Username
              </label>

              <input
                ref={
                  usernameRef
                }
                id="username"
                type="text"
                autoComplete="username"
                value={
                  username
                }
                disabled={
                  loading
                }
                onChange={(e) =>
                  setUsername(
                    e.target
                      .value
                  )
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none ring-blue-500/30 focus:border-blue-400 focus:ring-2"
                placeholder="username"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Password
              </label>

              <div className="relative">
                <input
                  id="password"
                  type={
                    showPassword
                      ? "text"
                      : "password"
                  }
                  autoComplete="current-password"
                  value={
                    password
                  }
                  disabled={
                    loading
                  }
                  onKeyUp={(
                    event
                  ) =>
                    setCapsLock(
                      event.getModifierState(
                        "CapsLock"
                      )
                    )
                  }
                  onChange={(e) =>
                    setPassword(
                      e.target
                        .value
                    )
                  }
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 pr-10 text-sm text-slate-900 outline-none ring-blue-500/30 focus:border-blue-400 focus:ring-2"
                  placeholder="••••••••"
                />

                <button
                  type="button"
                  onClick={() =>
                    setShowPassword(
                      (
                        value
                      ) =>
                        !value
                    )
                  }
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:text-slate-700"
                  aria-label={
                    showPassword
                      ? "Hide password"
                      : "Show password"
                  }
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>

              {capsLock && (
                <p className="mt-2 text-xs text-amber-600">
                  Caps Lock is enabled.
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={
                loading
              }
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-500/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" />
                  Sign In
                </>
              )}
            </button>
          </form>

          <div className="mt-6 border-t border-slate-100 pt-4 text-center">
            <p className="text-xs text-slate-400">
              Protected by JWT
              authentication, refresh-token
              rotation, CSRF validation, and
              secure HttpOnly cookies.
            </p>
          </div>
        </div>

        <p className="mt-6 text-center text-[11px] text-slate-400">
          Doc Intelligence Platform · Secure
          Enterprise Authentication
        </p>
      </div>
    </div>
  );
}