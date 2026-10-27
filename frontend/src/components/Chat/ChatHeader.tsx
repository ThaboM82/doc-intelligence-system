/**
 * ChatHeader — responsive top bar for RAG chat.
 */
import React, { useState } from 'react';
import {
  MessageSquare,
  Trash2,
  Settings2,
  Loader2,
  Shield,
  PanelRightOpen,
  PanelRightClose,
  Sparkles,
  FileStack,
  Wifi,
  WifiOff,
  AlertTriangle,
  StopCircle,
  MoreHorizontal,
} from 'lucide-react';

export type ChatConnectionStatus =
  | 'online'
  | 'degraded'
  | 'offline'
  | 'loading';

export type ChatHeaderProps = {
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  status?: ChatConnectionStatus;
  statusDetail?: string;
  modelLabel?: string;
  scopeLabel?: string;
  messageCount?: number;
  isStreaming?: boolean;
  citationsOpen?: boolean;
  citationCount?: number;
  busy?: boolean;
  onToggleCitations?: () => void;
  onClear?: () => void;
  onSettings?: () => void;
  onStop?: () => void;
  actions?: React.ReactNode;
  className?: string;
};

const STATUS: Record<
  ChatConnectionStatus,
  {
    label: string;
    text: string;
    bg: string;
    pulse: string;
    Icon: typeof Wifi;
  }
> = {
  online: {
    label: 'Online',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/15 border-emerald-400/25',
    pulse: 'bg-emerald-400',
    Icon: Wifi,
  },
  degraded: {
    label: 'Degraded',
    text: 'text-amber-300',
    bg: 'bg-amber-500/15 border-amber-400/25',
    pulse: 'bg-amber-400',
    Icon: AlertTriangle,
  },
  offline: {
    label: 'Offline',
    text: 'text-rose-300',
    bg: 'bg-rose-500/15 border-rose-400/25',
    pulse: 'bg-rose-400',
    Icon: WifiOff,
  },
  loading: {
    label: 'Connecting',
    text: 'text-slate-300',
    bg: 'bg-white/5 border-white/10',
    pulse: 'bg-slate-400',
    Icon: Loader2,
  },
};

function ToolbarButton({
  label,
  shortLabel,
  onClick,
  disabled,
  active,
  danger,
  children,
}: {
  label: string;
  shortLabel?: string;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled || !onClick}
      onClick={onClick}
      className={[
        'inline-flex h-9 items-center gap-1.5 rounded-xl border px-2.5 sm:px-3',
        'text-xs font-medium transition-all duration-150',
        'disabled:pointer-events-none disabled:opacity-40',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40',
        active
          ? 'border-violet-400/35 bg-violet-500/15 text-violet-200 shadow-[inset_0_0_0_1px_rgba(167,139,250,0.12)]'
          : danger
            ? 'border-white/10 bg-white/[0.04] text-slate-300 hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-200'
            : 'border-white/10 bg-white/[0.04] text-slate-300 hover:border-white/20 hover:bg-white/[0.07] hover:text-white',
      ].join(' ')}
    >
      {children}
      {shortLabel ? (
        <span className="hidden sm:inline">{shortLabel}</span>
      ) : null}
    </button>
  );
}

export default function ChatHeader({
  title = 'RAG Chat',
  subtitle = 'Ask questions grounded in your documents',
  eyebrow,
  status = 'online',
  statusDetail,
  modelLabel,
  scopeLabel,
  messageCount,
  isStreaming = false,
  citationsOpen,
  citationCount,
  busy = false,
  onToggleCitations,
  onClear,
  onSettings,
  onStop,
  actions,
  className = '',
}: ChatHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const s = STATUS[status];
  const StatusIcon = s.Icon;
  const helper =
    status !== 'online' && statusDetail ? statusDetail : subtitle;

  return (
    <header
      className={[
        'sticky top-0 z-20 border-b border-white/10',
        'bg-slate-950/90 backdrop-blur-xl',
        'supports-[backdrop-filter]:bg-slate-950/75',
        className,
      ].join(' ')}
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-3 py-3 sm:px-5 sm:py-3.5">
        {/* Row 1: identity + primary actions */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-blue-400/20 bg-gradient-to-br from-blue-500/20 to-indigo-500/10 shadow-[0_0_24px_rgba(59,130,246,0.12)]">
              {isStreaming ? (
                <Sparkles className="h-5 w-5 animate-pulse text-blue-200" />
              ) : (
                <MessageSquare className="h-5 w-5 text-blue-300" />
              )}
              <span
                className={[
                  'absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-950',
                  s.pulse,
                  status === 'online' ? 'animate-pulse' : '',
                ].join(' ')}
              />
            </div>

            <div className="min-w-0">
              {eyebrow ? (
                <p className="mb-0.5 truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  {eyebrow}
                </p>
              ) : null}

              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <h1 className="truncate text-base font-semibold tracking-tight text-white sm:text-lg">
                  {title}
                </h1>

                <span
                  className={[
                    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
                    s.bg,
                    s.text,
                  ].join(' ')}
                  title={statusDetail || s.label}
                >
                  {status === 'loading' ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <StatusIcon className="h-3 w-3" />
                  )}
                  {s.label}
                </span>

                {isStreaming ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-sky-400/25 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-200">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Generating
                  </span>
                ) : null}
              </div>

              <p className="mt-0.5 max-w-[42rem] truncate text-xs text-slate-500 sm:text-[13px]">
                {helper}
              </p>
            </div>
          </div>

          {/* Desktop actions */}
          <div className="hidden items-center gap-2 md:flex">
            {actions}

            {isStreaming && onStop ? (
              <ToolbarButton label="Stop generating" shortLabel="Stop" onClick={onStop} danger>
                <StopCircle className="h-4 w-4" />
              </ToolbarButton>
            ) : null}

            {onToggleCitations ? (
              <ToolbarButton
                label={citationsOpen ? 'Hide sources' : 'Show sources'}
                shortLabel="Sources"
                onClick={onToggleCitations}
                active={Boolean(citationsOpen)}
              >
                {citationsOpen ? (
                  <PanelRightClose className="h-4 w-4" />
                ) : (
                  <PanelRightOpen className="h-4 w-4" />
                )}
                {typeof citationCount === 'number' ? (
                  <span className="rounded-md bg-black/25 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-200">
                    {citationCount}
                  </span>
                ) : null}
              </ToolbarButton>
            ) : null}

            {onClear ? (
              <ToolbarButton
                label="Clear conversation"
                shortLabel="Clear"
                onClick={onClear}
                disabled={busy || isStreaming}
                danger
              >
                <Trash2 className="h-4 w-4" />
              </ToolbarButton>
            ) : null}

            {onSettings ? (
              <ToolbarButton label="Chat settings" onClick={onSettings} disabled={busy}>
                <Settings2 className="h-4 w-4" />
              </ToolbarButton>
            ) : null}
          </div>

          {/* Mobile overflow menu */}
          <div className="relative md:hidden">
            <ToolbarButton
              label="More actions"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <MoreHorizontal className="h-4 w-4" />
            </ToolbarButton>

            {menuOpen ? (
              <>
                <button
                  type="button"
                  className="fixed inset-0 z-30 cursor-default"
                  aria-label="Close menu"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="absolute right-0 z-40 mt-2 w-48 overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 p-1 shadow-2xl backdrop-blur-xl">
                  {isStreaming && onStop ? (
                    <MobileItem
                      icon={<StopCircle className="h-4 w-4" />}
                      label="Stop"
                      danger
                      onClick={() => {
                        onStop();
                        setMenuOpen(false);
                      }}
                    />
                  ) : null}
                  {onToggleCitations ? (
                    <MobileItem
                      icon={
                        citationsOpen ? (
                          <PanelRightClose className="h-4 w-4" />
                        ) : (
                          <PanelRightOpen className="h-4 w-4" />
                        )
                      }
                      label={citationsOpen ? 'Hide sources' : 'Show sources'}
                      onClick={() => {
                        onToggleCitations();
                        setMenuOpen(false);
                      }}
                    />
                  ) : null}
                  {onClear ? (
                    <MobileItem
                      icon={<Trash2 className="h-4 w-4" />}
                      label="Clear chat"
                      danger
                      disabled={busy || isStreaming}
                      onClick={() => {
                        onClear();
                        setMenuOpen(false);
                      }}
                    />
                  ) : null}
                  {onSettings ? (
                    <MobileItem
                      icon={<Settings2 className="h-4 w-4" />}
                      label="Settings"
                      disabled={busy}
                      onClick={() => {
                        onSettings();
                        setMenuOpen(false);
                      }}
                    />
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        </div>

        {/* Row 2: meta chips — wraps cleanly on small screens */}
        <div className="flex flex-wrap items-center gap-2">
          {scopeLabel ? (
            <MetaChip icon={<FileStack className="h-3.5 w-3.5" />}>
              <span className="max-w-[9rem] truncate sm:max-w-[14rem]">
                {scopeLabel}
              </span>
            </MetaChip>
          ) : null}

          {modelLabel ? (
            <MetaChip icon={<Shield className="h-3.5 w-3.5" />}>
              {modelLabel}
            </MetaChip>
          ) : null}

          {typeof messageCount === 'number' ? (
            <MetaChip>
              <span className="tabular-nums">{messageCount}</span>
              <span className="text-slate-500">
                message{messageCount === 1 ? '' : 's'}
              </span>
            </MetaChip>
          ) : null}

          {/* Mobile-only quick sources toggle */}
          {onToggleCitations ? (
            <div className="ml-auto md:hidden">
              <ToolbarButton
                label={citationsOpen ? 'Hide sources' : 'Show sources'}
                shortLabel="Sources"
                onClick={onToggleCitations}
                active={Boolean(citationsOpen)}
              >
                {citationsOpen ? (
                  <PanelRightClose className="h-4 w-4" />
                ) : (
                  <PanelRightOpen className="h-4 w-4" />
                )}
                {typeof citationCount === 'number' ? (
                  <span className="tabular-nums text-[10px]">{citationCount}</span>
                ) : null}
              </ToolbarButton>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function MetaChip({
  icon,
  children,
}: {
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-white/8 bg-white/[0.035] px-2.5 py-1 text-[11px] text-slate-400">
      {icon ? <span className="shrink-0 text-slate-500">{icon}</span> : null}
      {children}
    </span>
  );
}

function MobileItem({
  icon,
  label,
  onClick,
  disabled,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        'flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition',
        'disabled:opacity-40',
        danger
          ? 'text-rose-300 hover:bg-rose-500/10'
          : 'text-slate-200 hover:bg-white/5',
      ].join(' ')}
    >
      {icon}
      {label}
    </button>
  );
}