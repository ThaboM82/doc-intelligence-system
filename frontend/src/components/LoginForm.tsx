/**
 * LoginForm — email/password (/api/v1/auth), optional JWT paste, demo session.
 */
import React, { useState } from 'react';
import {
  Shield,
  Key,
  Sparkles,
  AlertCircle,
  Loader2,
  Mail,
  Lock,
  UserPlus,
  LogIn,
} from 'lucide-react';
import { apiClient } from '../lib/apiClient';

const AUTH_STORAGE_KEY = 'doc_intel_access_token';
const AUTH_STORAGE_LEGACY = 'doc_intelligence_token';

type Mode = 'login' | 'register';

type Props = {
  onLoginSuccess?: (token: string) => void;
  allowDemo?: boolean;
};

function errorText(err: unknown): string {
  const e = err as {
    message?: unknown;
    detail?: unknown;
    status?: number;
    code?: string;
  };
  if (e?.code === 'CIRCUIT_OPEN') {
    return 'API circuit is open. Wait a few seconds and retry (Render may be waking up).';
  }
  const d = e?.detail ?? e?.message;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object') {
    try {
      return JSON.stringify(d);
    } catch {
      /* ignore */
    }
  }
  return 'Authentication failed. Check credentials, CORS, and VITE_API_URL.';
}

export default function LoginForm({ onLoginSuccess, allowDemo = true }: Props) {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [showAdvancedToken, setShowAdvancedToken] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apiBase =
    (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ||
    (typeof apiClient.getBaseUrl === 'function'
      ? apiClient.getBaseUrl()
      : 'http://localhost:8000');

  const finish = (token: string) => {
    if (typeof apiClient.setAuthToken === 'function') {
      apiClient.setAuthToken(token);
    }
    try {
      localStorage.setItem(AUTH_STORAGE_KEY, token);
      localStorage.setItem(AUTH_STORAGE_LEGACY, token);
      localStorage.setItem('auth_token', token);
    } catch {
      /* ignore */
    }
    onLoginSuccess?.(token);
  };

  const handleCredentialSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const em = email.trim().toLowerCase();
    if (!em || !password) {
      setError('Email and password are required.');
      setLoading(false);
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      setLoading(false);
      return;
    }

    try {
      if (mode === 'register') {
        await apiClient.register({
          email: em,
          password,
          full_name: fullName.trim() || undefined,
        });
        const tok = await apiClient.login({ email: em, password });
        finish(tok.access_token);
      } else {
        const tok = await apiClient.login({ email: em, password });
        finish(tok.access_token);
      }
    } catch (err) {
      console.error(err);
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const handleTokenPaste = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const activeToken = tokenInput.trim();
    if (!activeToken) {
      setError('Paste a JWT access_token first.');
      setLoading(false);
      return;
    }

    try {
      apiClient.setAuthToken(activeToken);
      try {
        await apiClient.me();
      } catch {
        await apiClient.getHealth();
      }
      finish(activeToken);
    } catch (err) {
      console.error(err);
      apiClient.setAuthToken(null);
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDemoLogin = async () => {
    if (!allowDemo) return;
    setLoading(true);
    setError(null);
    try {
      try {
        const tok = await apiClient.login({
          email: 'demo@docintel.local',
          password: 'demo-password-change-me',
        });
        finish(tok.access_token);
        return;
      } catch {
        /* fall through */
      }

      await apiClient.getHealth();
      finish('demo_local_session');
    } catch (err) {
      setError(
        `${errorText(err)} — Start the API or set VITE_API_URL to your Render service.`
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex p-3 bg-blue-600/10 border border-blue-500/20 rounded-xl text-blue-400 shadow-inner">
            <Shield className="w-8 h-8" />
          </div>
          <h2 className="text-xl font-bold text-slate-100 tracking-tight">
            Enterprise Document Intelligence
          </h2>
          <p className="text-xs text-slate-400">
            Secure RAG, threat telemetry &amp; vector analytics
          </p>
          <p className="text-[10px] text-slate-600 font-mono truncate" title={apiBase}>
            API: {apiBase}
          </p>
        </div>

        {error && (
          <div className="p-3 bg-red-950/40 border border-red-800/50 rounded-lg flex items-start space-x-2 text-red-300 text-xs">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-red-400 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex rounded-lg border border-slate-800 p-1 bg-slate-950/50">
          <button
            type="button"
            onClick={() => setMode('login')}
            className={`flex-1 py-2 text-xs font-semibold rounded-md transition ${
              mode === 'login'
                ? 'bg-slate-800 text-blue-300'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className="inline-flex items-center gap-1.5 justify-center w-full">
              <LogIn className="w-3.5 h-3.5" /> Sign in
            </span>
          </button>
          <button
            type="button"
            onClick={() => setMode('register')}
            className={`flex-1 py-2 text-xs font-semibold rounded-md transition ${
              mode === 'register'
                ? 'bg-slate-800 text-blue-300'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className="inline-flex items-center gap-1.5 justify-center w-full">
              <UserPlus className="w-3.5 h-3.5" /> Register
            </span>
          </button>
        </div>

        <form onSubmit={(e) => void handleCredentialSubmit(e)} className="space-y-3">
          {mode === 'register' && (
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Full name</label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                placeholder="Optional"
              />
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs text-slate-400">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-3 w-4 h-4 text-slate-500" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-10 pr-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                placeholder="you@company.com"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-3 w-4 h-4 text-slate-500" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength={8}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-10 pr-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                placeholder="••••••••"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition flex items-center justify-center space-x-2 shadow-lg shadow-blue-600/20 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : mode === 'login' ? (
              <LogIn className="w-4 h-4" />
            ) : (
              <UserPlus className="w-4 h-4" />
            )}
            <span>
              {loading
                ? 'Please wait…'
                : mode === 'login'
                  ? 'Sign in'
                  : 'Create account'}
            </span>
          </button>
        </form>

        {allowDemo && (
          <button
            type="button"
            disabled={loading}
            onClick={() => void handleDemoLogin()}
            className="w-full py-2.5 px-4 bg-slate-800 border border-slate-700 text-slate-200 text-sm font-medium rounded-lg transition flex items-center justify-center space-x-2 disabled:opacity-50 hover:bg-slate-750"
          >
            <Sparkles className="w-4 h-4 text-blue-400" />
            <span>Continue with demo session</span>
          </button>
        )}

        <div className="text-center">
          <button
            type="button"
            onClick={() => setShowAdvancedToken((v) => !v)}
            className="text-xs text-slate-500 hover:text-slate-400 transition underline underline-offset-4"
          >
            {showAdvancedToken ? 'Hide advanced token' : 'Paste JWT / API token'}
          </button>
        </div>

        {showAdvancedToken && (
          <form
            onSubmit={(e) => void handleTokenPaste(e)}
            className="pt-2 border-t border-slate-800 space-y-2"
          >
            <label className="block text-xs font-medium text-slate-400">
              Bearer access_token
            </label>
            <div className="relative">
              <Key className="absolute left-3 top-3 w-4 h-4 text-slate-500" />
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="eyJhbGciOiJIUzI1NiIs..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-10 pr-4 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !tokenInput.trim()}
              className="w-full py-2 rounded-lg bg-slate-800 border border-slate-700 text-xs font-semibold text-slate-200 disabled:opacity-50"
            >
              Use this token
            </button>
          </form>
        )}

        <div className="pt-2 border-t border-slate-800/60 text-center space-y-1">
          <span className="text-[11px] text-slate-500 font-mono block">
            Auth: POST /api/v1/auth/login · /register
          </span>
          <span className="text-[11px] text-slate-600">
            First registered user may become admin if the backend is configured that way.
          </span>
        </div>
      </div>
    </div>
  );
}