/**
 * LoginForm — enterprise auth shell (login · sign-up · forgot password · MFA).
 * frontend/src/components/LoginForm.tsx
 */
import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
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
  AlertTriangle,
  Clock,
  KeyRound,
  ArrowLeft,
  UserPlus,
  Mail,
  CheckCircle2,
} from "lucide-react";
import authService from "../services/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SsoProviderId = "google" | "microsoft" | "github";

type SsoProvider = {
  id: SsoProviderId;
  label: string;
  authorizePath: string;
};

type SsoProviderMap = Record<SsoProviderId, SsoProvider>;

type MfaChallenge = {
  mfa_token: string;
  methods: Array<"totp" | "recovery">;
  masked_hint?: string;
};

type AuthView =
  | { kind: "login" }
  | { kind: "signup" }
  | { kind: "forgot" }
  | { kind: "forgot-sent"; email: string }
  | { kind: "mfa"; challenge: MfaChallenge };

export type LoginFormProps = {
  onLoginSuccess?: () => void;
  maxAttempts?: number;
  lockoutMs?: number;
  enableSso?: boolean;
  ssoProviders?: SsoProviderId[];
  enableRememberMe?: boolean;
  enableSignUp?: boolean;
  onSsoStart?: (provider: SsoProviderId) => void;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_LOCKOUT_MS = 30_000;
const HEALTH_POLL_MS = 45_000;
const REMEMBER_KEY = "doc_intel_remember_identity";

const SSO_CATALOG: SsoProviderMap = {
  google: {
    id: "google",
    label: "Google",
    authorizePath: "/api/v1/auth/sso/google/authorize",
  },
  microsoft: {
    id: "microsoft",
    label: "Microsoft",
    authorizePath: "/api/v1/auth/sso/microsoft/authorize",
  },
  github: {
    id: "github",
    label: "GitHub",
    authorizePath: "/api/v1/auth/sso/github/authorize",
  },
};

const EMAIL_RE =
  /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;

function isEmailLike(value: string): boolean {
  return value.includes("@");
}

function isValidEmail(value: string): boolean {
  if (value.length > 254) return false;
  return EMAIL_RE.test(value);
}

function validateIdentity(value: string): string | null {
  const v = value.trim();
  if (!v) return "Email or username is required.";
  if (v.length > 128) return "Email or username is too long.";
  if (isEmailLike(v) && !isValidEmail(v)) {
    return "Enter a valid email address.";
  }
  return null;
}

function validateEmailRequired(value: string): string | null {
  const v = value.trim();
  if (!v) return "Email is required.";
  if (!isValidEmail(v)) return "Enter a valid email address.";
  return null;
}

function validatePasswordStrength(password: string): string | null {
  if (!password) return "Password is required.";
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (password.length > 512) return "Password exceeds maximum length.";
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return "Password must include letters and numbers.";
  }
  return null;
}

function getFriendlyError(error: unknown): string {
  const err = error as {
    code?: string;
    name?: string;
    message?: string;
    response?: {
      status?: number;
      data?: { detail?: unknown; message?: string };
    };
  };

  if (err?.name === "AbortError" || err?.code === "ERR_CANCELED") {
    return "Request cancelled.";
  }
  if (err?.code === "ERR_NETWORK") {
    return "Unable to reach authentication service. Check network and API URL.";
  }
  if (err?.code === "ECONNABORTED") {
    return "Request timed out. Please retry.";
  }

  const status = err?.response?.status;
  switch (status) {
    case 400:
      return "Invalid request. Check your input.";
    case 401:
      return "Invalid email/username or password.";
    case 403:
      return "Access denied. Your account may be disabled.";
    case 409:
      return "An account with this email already exists.";
    case 422:
      return "Validation failed. Check your details.";
    case 429:
      return "Too many attempts. Please wait and try again.";
    case 503:
      return "Authentication service temporarily unavailable.";
    default:
      break;
  }
  if (status && status >= 500) {
    return "Authentication service unavailable. Try again later.";
  }

  const detail = err?.response?.data?.detail;
  if (
    typeof detail === "string" &&
    detail.length < 200 &&
    !detail.includes("Traceback")
  ) {
    return detail;
  }
  if (
    typeof err?.message === "string" &&
    err.message.length < 200 &&
    !err.message.includes("at ")
  ) {
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

function extractMfaChallenge(error: unknown): MfaChallenge | null {
  const data = (
    error as {
      response?: {
        data?: {
          mfa_required?: boolean;
          mfa_token?: string;
          methods?: Array<"totp" | "recovery">;
          detail?: string;
        };
      };
    }
  )?.response?.data;

  if (!data?.mfa_required || !data.mfa_token) return null;
  return {
    mfa_token: data.mfa_token,
    methods: data.methods?.length ? data.methods : ["totp"],
    masked_hint: typeof data.detail === "string" ? data.detail : undefined,
  };
}
// ---------------------------------------------------------------------------
// Shared UI
// ---------------------------------------------------------------------------

function BrandHeader({
  title,
  subtitle,
  icon = "shield",
}: {
  title: string;
  subtitle: string;
  icon?: "shield" | "key" | "mail" | "user";
}) {
  const Icon =
    icon === "key"
      ? KeyRound
      : icon === "mail"
        ? Mail
        : icon === "user"
          ? UserPlus
          : ShieldCheck;
  return (
    <div className="mb-8 text-center">
      <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-500/30">
        <Icon className="h-8 w-8" aria-hidden />
      </div>
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">
        {title}
      </h1>
      <p className="mt-2 text-sm text-slate-500">{subtitle}</p>
    </div>
  );
}

function StatusRow({ apiHealthy }: { apiHealthy: boolean | null }) {
  return (
    <div className="mb-6 flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm" aria-live="polite">
        {apiHealthy === null ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
            <span className="text-slate-500">Checking API…</span>
          </>
        ) : apiHealthy ? (
          <>
            <Wifi className="h-4 w-4 text-emerald-500" aria-hidden />
            <span className="text-emerald-600">API Online</span>
          </>
        ) : (
          <>
            <WifiOff className="h-4 w-4 text-red-500" aria-hidden />
            <span className="text-red-600">API Offline</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-1 text-xs text-slate-500">
        <Lock className="h-3 w-3" aria-hidden />
        Secure session
      </div>
    </div>
  );
}

function ErrorBanner({ id, message }: { id?: string; message: string }) {
  return (
    <div
      id={id}
      role="alert"
      className="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-800"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

function fieldClass(disabled?: boolean) {
  return [
    "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none",
    "ring-blue-500/30 placeholder:text-slate-400 focus:border-blue-400 focus:ring-2",
    disabled
      ? "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-70"
      : "",
  ].join(" ");
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50 px-4 py-10">
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xl shadow-slate-200/60">
      {children}
    </div>
  );
}

function Footer() {
  return (
    <p className="mt-6 text-center text-[11px] text-slate-400">
      Doc Intelligence Platform · Enterprise Authentication
    </p>
  );
}

function OfflineBanner({ baseUrl }: { baseUrl: string }) {
  return (
    <div
      role="status"
      className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        Cannot reach the API at{" "}
        <code className="rounded bg-white/70 px-1 text-xs">{baseUrl}</code>.
        Actions are disabled until the service is available.
      </span>
    </div>
  );
}

function TogglePassword({
  show,
  onToggle,
}: {
  show: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-slate-400 hover:text-slate-700"
      aria-label={show ? "Hide password" : "Show password"}
      tabIndex={-1}
    >
      {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
    </button>
  );
}

function PrimaryButton({
  loading,
  disabled,
  label,
  loadingLabel,
  icon,
}: {
  loading: boolean;
  disabled?: boolean;
  label: string;
  loadingLabel: string;
  icon?: "shield" | "mail" | "user";
}) {
  const Icon =
    icon === "mail" ? Mail : icon === "user" ? UserPlus : ShieldCheck;
  return (
    <button
      type="submit"
      disabled={loading || disabled}
      className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-500/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {loadingLabel}
        </>
      ) : (
        <>
          <Icon className="h-4 w-4" aria-hidden />
          {label}
        </>
      )}
    </button>
  );
}

function SecondaryButton({
  onClick,
  label,
}: {
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
    >
      <ArrowLeft className="h-4 w-4" />
      {label}
    </button>
  );
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LoginForm({
  onLoginSuccess,
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
  lockoutMs = DEFAULT_LOCKOUT_MS,
  enableSso = true,
  ssoProviders = ["google", "microsoft", "github"],
  enableRememberMe = true,
  enableSignUp = true,
  onSsoStart,
}: LoginFormProps) {
  const usernameId = useId();
  const passwordId = useId();
  const password2Id = useId();
  const emailId = useId();
  const mfaId = useId();
  const formErrorId = useId();
  const rememberId = useId();

  const [view, setView] = useState<AuthView>({ kind: "login" });
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  const [loginAttempts, setLoginAttempts] = useState(0);
  const [capsLock, setCapsLock] = useState(false);
  const [lockoutUntil, setLockoutUntil] = useState<number | null>(null);
  const [lockoutRemaining, setLockoutRemaining] = useState(0);
  const [mfaCode, setMfaCode] = useState("");
  const [ssoLoading, setSsoLoading] = useState<SsoProviderId | null>(null);

  const usernameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const mfaRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const activeSso = useMemo(
    () =>
      enableSso
        ? ssoProviders.map((id) => SSO_CATALOG[id]).filter(Boolean)
        : [],
    [enableSso, ssoProviders]
  );

  useEffect(() => {
    try {
      const saved = localStorage.getItem(REMEMBER_KEY);
      if (saved) {
        setUsername(saved);
        setRememberMe(true);
      }
    } catch {
      /* private mode */
    }
    usernameRef.current?.focus();
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await authService.health();
        if (!cancelled && mountedRef.current) setApiHealthy(true);
      } catch {
        if (!cancelled && mountedRef.current) setApiHealthy(false);
      }
    };
    void check();
    const id = window.setInterval(() => void check(), HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (lockoutUntil == null) {
      setLockoutRemaining(0);
      return;
    }
    const tick = () => {
      const left = Math.max(0, lockoutUntil - Date.now());
      setLockoutRemaining(left);
      if (left <= 0) {
        setLockoutUntil(null);
        setLoginAttempts(0);
      }
    };
    tick();
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [lockoutUntil]);

  useEffect(() => {
    if (view.kind === "mfa") mfaRef.current?.focus();
    if (view.kind === "forgot" || view.kind === "signup")
      emailRef.current?.focus();
    if (view.kind === "login") usernameRef.current?.focus();
  }, [view.kind]);

  const lockedOut = lockoutUntil != null && lockoutRemaining > 0;
  const busy = loading || lockedOut || apiHealthy === false;
  const lockoutSeconds = Math.ceil(lockoutRemaining / 1000);

  const go = (next: AuthView) => {
    setError(null);
    setPassword("");
    setPassword2("");
    setMfaCode("");
    setView(next);
  };

  const persistRemember = useCallback(
    (identity: string) => {
      try {
        if (rememberMe && identity) localStorage.setItem(REMEMBER_KEY, identity);
        else localStorage.removeItem(REMEMBER_KEY);
      } catch {
        /* ignore */
      }
    },
    [rememberMe]
  );

  const finishSuccess = useCallback(
    (identity: string) => {
      persistRemember(identity);
      setPassword("");
      setMfaCode("");
      setLoginAttempts(0);
      onLoginSuccess?.();
    },
    [onLoginSuccess, persistRemember]
  );

  const handleLogin = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (loading || lockedOut) return;
      setError(null);

      const u = username.trim();
      const identityError = validateIdentity(u);
      if (identityError) {
        setError(identityError);
        return;
      }
      if (!password) {
        setError("Password is required.");
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);

      try {
        const result = await authService.login(u, password, controller.signal);
        const maybeMfa = result as {
          mfa_required?: boolean;
          mfa_token?: string;
          methods?: Array<"totp" | "recovery">;
        };
        if (maybeMfa.mfa_required && maybeMfa.mfa_token) {
          setView({
            kind: "mfa",
            challenge: {
              mfa_token: maybeMfa.mfa_token,
              methods: maybeMfa.methods?.length
                ? maybeMfa.methods
                : ["totp"],
            },
          });
          setPassword("");
          return;
        }
        await authService.me(controller.signal);
        if (!mountedRef.current) return;
        finishSuccess(u);
      } catch (err) {
        if (!mountedRef.current) return;
        if (
          (err as { name?: string })?.name === "AbortError" ||
          (err as { code?: string })?.code === "ERR_CANCELED"
        ) {
          return;
        }
        const challenge = extractMfaChallenge(err);
        if (challenge) {
          setView({ kind: "mfa", challenge });
          setPassword("");
          return;
        }
        const nextAttempts = loginAttempts + 1;
        setLoginAttempts(nextAttempts);
        setError(getFriendlyError(err));
        setPassword("");
        if (nextAttempts >= maxAttempts) {
          setLockoutUntil(Date.now() + lockoutMs);
        }
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [
      username,
      password,
      loading,
      lockedOut,
      loginAttempts,
      maxAttempts,
      lockoutMs,
      finishSuccess,
    ]
  );
    const handleMfa = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (loading || lockedOut || view.kind !== "mfa") return;
      setError(null);
      const code = mfaCode.replace(/\s/g, "");
      if (!code || code.length < 6) {
        setError("Enter the 6-digit code from your authenticator app.");
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);

      try {
        await (authService as typeof authService & {
          verifyMfa: (
            token: string,
            code: string,
            signal: AbortSignal
          ) => Promise<unknown>;
        }).verifyMfa(
          view.challenge.mfa_token,
          code,
          controller.signal
        );
        await authService.me(controller.signal);
        if (!mountedRef.current) return;
        finishSuccess(username.trim());
      } catch (err) {
        if (!mountedRef.current) return;
        if (
          (err as { name?: string })?.name === "AbortError" ||
          (err as { code?: string })?.code === "ERR_CANCELED"
        ) {
          return;
        }
        setError(getFriendlyError(err));
        setMfaCode("");
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [loading, lockedOut, view, mfaCode, username, finishSuccess]
  );

  const handleSignUp = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (loading || lockedOut) return;
      setError(null);

      const em = email.trim();
      const emailErr = validateEmailRequired(em);
      if (emailErr) {
        setError(emailErr);
        return;
      }
      const pwErr = validatePasswordStrength(password);
      if (pwErr) {
        setError(pwErr);
        return;
      }
      if (password !== password2) {
        setError("Passwords do not match.");
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);

      try {
        await authService.register(em, password, controller.signal);
        try {
          await authService.login(em, password, controller.signal);
          await authService.me(controller.signal);
          if (!mountedRef.current) return;
          finishSuccess(em);
          return;
        } catch {
          setPassword("");
          setPassword2("");
          setUsername(em);
          setView({ kind: "login" });
          setError(null);
        }
      } catch (err) {
        if (!mountedRef.current) return;
        if (
          (err as { name?: string })?.name === "AbortError" ||
          (err as { code?: string })?.code === "ERR_CANCELED"
        ) {
          return;
        }
        setError(getFriendlyError(err));
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [email, password, password2, loading, lockedOut, finishSuccess]
  );

  const handleForgot = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (loading) return;
      setError(null);

      const em = email.trim();
      const emailErr = validateEmailRequired(em);
      if (emailErr) {
        setError(emailErr);
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);

      try {
        const response = await fetch("/api/v1/auth/forgot-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: em }),
            signal: controller.signal,
          });
        if (!response.ok && response.status !== 404) {
          throw Object.assign(new Error("Password reset request failed."), {
            response: { status: response.status },
          });
        }
        if (!mountedRef.current) return;
        setView({ kind: "forgot-sent", email: em });
      } catch (err) {
        if (!mountedRef.current) return;
        if (
          (err as { name?: string })?.name === "AbortError" ||
          (err as { code?: string })?.code === "ERR_CANCELED"
        ) {
          return;
        }
        const status = (err as { response?: { status?: number } })?.response
          ?.status;
        if (status === 404 || status === 200 || !status) {
          setView({ kind: "forgot-sent", email: em });
          return;
        }
        setError(getFriendlyError(err));
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [email, loading]
  );

  const handleSso = (provider: SsoProviderId) => {
    if (apiHealthy === false || lockedOut) return;
    const meta = SSO_CATALOG[provider];
    if (!meta) return;
    onSsoStart?.(provider);
    setSsoLoading(provider);
    const url = meta.authorizePath.startsWith("http")
      ? meta.authorizePath
      : meta.authorizePath;
    window.location.assign(url);
  };
    if (view.kind === "mfa") {
    return (
      <Shell>
        <BrandHeader
          title="Two-factor authentication"
          subtitle={
            view.challenge.masked_hint ||
            "Enter the code from your authenticator app."
          }
          icon="key"
        />
        <Card>
          {error && <ErrorBanner id={formErrorId} message={error} />}
          <form
            onSubmit={(e) => void handleMfa(e)}
            className="space-y-4"
            noValidate
          >
            <div>
              <label
                htmlFor={mfaId}
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Authentication code
              </label>
              <input
                ref={mfaRef}
                id={mfaId}
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                value={mfaCode}
                disabled={loading}
                onChange={(e) => setMfaCode(e.target.value)}
                className={`${fieldClass(loading)} text-center font-mono text-lg tracking-widest`}
                placeholder="000000"
                required
              />
              <p className="mt-1 text-[11px] text-slate-400">
                Methods: {view.challenge.methods.join(", ")}
              </p>
            </div>
            <PrimaryButton
              loading={loading}
              label="Verify and continue"
              loadingLabel="Verifying…"
              icon="shield"
            />
            <SecondaryButton
              onClick={() => go({ kind: "login" })}
              label="Back to sign in"
            />
          </form>
        </Card>
      </Shell>
    );
  }

  if (view.kind === "forgot-sent") {
    return (
      <Shell>
        <BrandHeader
          title="Check your email"
          subtitle={`If an account exists for ${view.email}, we sent reset instructions.`}
          icon="mail"
        />
        <Card>
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-900">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Password reset email sent (if the address is registered). Check
              spam/junk folders.
            </span>
          </div>
          <SecondaryButton
            onClick={() => go({ kind: "login" })}
            label="Back to sign in"
          />
        </Card>
      </Shell>
    );
  }

  if (view.kind === "forgot") {
    return (
      <Shell>
        <BrandHeader
          title="Reset password"
          subtitle="Enter your work email and we will send a secure reset link."
          icon="mail"
        />
        <Card>
          <StatusRow apiHealthy={apiHealthy} />
          {apiHealthy === false && (
            <OfflineBanner baseUrl={authService.getBaseUrl()} />
          )}
          {error && <ErrorBanner id={formErrorId} message={error} />}
          <form
            onSubmit={(e) => void handleForgot(e)}
            className="space-y-4"
            noValidate
          >
            <div>
              <label
                htmlFor={emailId}
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Email
              </label>
              <input
                ref={emailRef}
                id={emailId}
                type="email"
                autoComplete="email"
                value={email}
                disabled={loading || apiHealthy === false}
                onChange={(e) => setEmail(e.target.value)}
                className={fieldClass(loading)}
                placeholder="name@company.com"
                required
                maxLength={254}
              />
            </div>
            <PrimaryButton
              loading={loading}
              disabled={apiHealthy === false}
              label="Send reset link"
              loadingLabel="Sending…"
              icon="mail"
            />
            <SecondaryButton
              onClick={() => go({ kind: "login" })}
              label="Back to sign in"
            />
          </form>
        </Card>
        <Footer />
      </Shell>
    );
  }
    if (view.kind === "signup") {
    return (
      <Shell>
        <BrandHeader
          title="Create account"
          subtitle="Register for Doc Intelligence with your work email."
          icon="user"
        />
        <Card>
          <StatusRow apiHealthy={apiHealthy} />
          {apiHealthy === false && (
            <OfflineBanner baseUrl={authService.getBaseUrl()} />
          )}
          {error && <ErrorBanner id={formErrorId} message={error} />}
          <form
            onSubmit={(e) => void handleSignUp(e)}
            className="space-y-4"
            noValidate
          >
            <div>
              <label
                htmlFor={emailId}
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Work email
              </label>
              <input
                ref={emailRef}
                id={emailId}
                type="email"
                autoComplete="email"
                value={email}
                disabled={busy}
                onChange={(e) => setEmail(e.target.value)}
                className={fieldClass(busy)}
                placeholder="name@company.com"
                required
                maxLength={254}
              />
            </div>
            <div>
              <label
                htmlFor={passwordId}
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Password
              </label>
              <div className="relative">
                <input
                  id={passwordId}
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={password}
                  disabled={busy}
                  onChange={(e) => setPassword(e.target.value)}
                  className={`${fieldClass(busy)} pr-10`}
                  placeholder="Min. 8 chars, letters + numbers"
                  required
                  maxLength={512}
                />
                <TogglePassword
                  show={showPassword}
                  onToggle={() => setShowPassword((v) => !v)}
                />
              </div>
            </div>
            <div>
              <label
                htmlFor={password2Id}
                className="mb-1 block text-xs font-semibold text-slate-600"
              >
                Confirm password
              </label>
              <input
                id={password2Id}
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={password2}
                disabled={busy}
                onChange={(e) => setPassword2(e.target.value)}
                className={fieldClass(busy)}
                placeholder="Re-enter password"
                required
                maxLength={512}
              />
            </div>
            <PrimaryButton
              loading={loading}
              disabled={busy}
              label="Create account"
              loadingLabel="Creating…"
              icon="user"
            />
            <p className="text-center text-xs text-slate-500">
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => go({ kind: "login" })}
                className="font-semibold text-blue-600 hover:text-blue-700 hover:underline"
              >
                Sign in
              </button>
            </p>
          </form>
        </Card>
        <Footer />
      </Shell>
    );
  }
   return (
    <Shell>
      <BrandHeader
        title="Doc Intelligence"
        subtitle="Secure access to document ingestion, search, governance, and AI intelligence services."
      />
      <Card>
        <StatusRow apiHealthy={apiHealthy} />
        {apiHealthy === false && (
          <OfflineBanner baseUrl={authService.getBaseUrl()} />
        )}
        {error && <ErrorBanner id={formErrorId} message={error} />}
        {loginAttempts >= 3 && !lockedOut && (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900">
            Multiple failed sign-in attempts detected. Further failures will
            temporarily lock this form.
          </div>
        )}
        {lockedOut && (
          <div
            role="status"
            className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900"
          >
            <Clock className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Too many failed attempts. Try again in{" "}
              <strong>{lockoutSeconds}s</strong>.
            </span>
          </div>
        )}

        <form
          onSubmit={(e) => void handleLogin(e)}
          className="space-y-4"
          noValidate
          aria-describedby={error ? formErrorId : undefined}
        >
          <div>
            <label
              htmlFor={usernameId}
              className="mb-1 block text-xs font-semibold text-slate-600"
            >
              Email or username
            </label>
            <input
              ref={usernameRef}
              id={usernameId}
              name="username"
              type="text"
              autoComplete="username"
              inputMode="email"
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
              value={username}
              disabled={busy}
              onChange={(e) => setUsername(e.target.value)}
              onBlur={() => {
                const msg = validateIdentity(username);
                if (msg && username.trim()) setError(msg);
              }}
              className={fieldClass(busy)}
              placeholder="name@company.com"
              required
              maxLength={128}
            />
          </div>

          <div>
            <label
              htmlFor={passwordId}
              className="mb-1 block text-xs font-semibold text-slate-600"
            >
              Password
            </label>
            <div className="relative">
              <input
                id={passwordId}
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                disabled={busy}
                onKeyUp={(event) =>
                  setCapsLock(event.getModifierState("CapsLock"))
                }
                onKeyDown={(event) =>
                  setCapsLock(event.getModifierState("CapsLock"))
                }
                onChange={(e) => setPassword(e.target.value)}
                className={`${fieldClass(busy)} pr-10`}
                placeholder="••••••••"
                required
                maxLength={512}
              />
              <TogglePassword
                show={showPassword}
                onToggle={() => setShowPassword((v) => !v)}
              />
            </div>
            {capsLock && (
              <p className="mt-2 text-xs text-amber-600" role="status">
                Caps Lock is enabled.
              </p>
            )}

            <div className="mt-2 flex items-center justify-between gap-2">
              {enableRememberMe ? (
                <label
                  htmlFor={rememberId}
                  className="flex cursor-pointer items-center gap-2 text-xs text-slate-600"
                >
                  <input
                    id={rememberId}
                    type="checkbox"
                    checked={rememberMe}
                    disabled={busy}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  Remember me
                </label>
              ) : (
                <span />
              )}
              <button
                type="button"
                onClick={() => {
                  setEmail(
                    isValidEmail(username.trim()) ? username.trim() : ""
                  );
                  go({ kind: "forgot" });
                }}
                className="text-xs font-semibold text-blue-600 underline-offset-2 hover:text-blue-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
              >
                Forgot password?
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-500/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Signing in…
              </>
            ) : lockedOut ? (
              <>
                <Clock className="h-4 w-4" aria-hidden />
                Locked ({lockoutSeconds}s)
              </>
            ) : (
              <>
                <LogIn className="h-4 w-4" aria-hidden />
                Sign In
              </>
            )}
          </button>
        </form>

        {activeSso.length > 0 && (
          <>
            <div className="my-5 flex items-center gap-3 text-[11px] text-slate-400">
              <span className="h-px flex-1 bg-slate-200" />
              or continue with
              <span className="h-px flex-1 bg-slate-200" />
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {activeSso.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  disabled={busy || ssoLoading !== null}
                  onClick={() => handleSso(p.id)}
                  className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {ssoLoading === p.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  {p.label}
                </button>
              ))}
            </div>
          </>
        )}

        {enableSignUp && (
          <p className="mt-5 text-center text-xs text-slate-500">
            No account?{" "}
            <button
              type="button"
              onClick={() => go({ kind: "signup" })}
              className="font-semibold text-blue-600 hover:text-blue-700 hover:underline"
            >
              Create one
            </button>
          </p>
        )}

        <div className="mt-6 border-t border-slate-100 pt-4 text-center">
          <p className="text-xs text-slate-400">
            Protected by JWT authentication, optional MFA, SSO, and secure
            session handling. Passwords are never stored in this browser.
          </p>
        </div>
      </Card>
      <Footer />
    </Shell>
  );
}
 