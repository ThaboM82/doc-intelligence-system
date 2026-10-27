import { useMemo } from "react";
import {
  ShieldAlert,
  AlertTriangle,
  Activity,
  CheckCircle2,
  ShieldCheck,
  FileWarning,
  TrendingUp,
} from "lucide-react";

import { threatEvents, quarantinedFiles, securityStats } from "./data";
import type { ThreatEvent } from "./types";

/* ────────────────────────────────────────────────────────────────────────── */
/* Types                                                                      */
/* ────────────────────────────────────────────────────────────────────────── */

interface ThreatSummaryProps {
  events?: ThreatEvent[];
  quarantinedCount?: number;
  isLoading?: boolean;
}

interface SummaryCard {
  id: string;
  label: string;
  value: string | number;
  description: string;
  icon: React.ElementType;
  iconColor: string;
  iconBg: string;
  ring: string;
  accent: string;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Component                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

const ThreatSummary = ({
  events = threatEvents,
  quarantinedCount = quarantinedFiles.length,
  isLoading = false,
}: ThreatSummaryProps) => {
  const metrics = useMemo(() => {
    const open = events.filter(
      (e) => e.status === "Open" || e.status === "Investigating"
    ).length;
    const critical = events.filter((e) => e.severity === "Critical").length;
    const high = events.filter((e) => e.severity === "High").length;
    const resolved = events.filter((e) => e.status === "Resolved").length;
    const total = events.length;

    const resolutionRate =
      total > 0 ? Math.round((resolved / total) * 100) : 0;

    return {
      total,
      open,
      critical,
      high,
      resolved,
      quarantined: quarantinedCount,
      resolutionRate,
    };
  }, [events, quarantinedCount]);

  const cards: SummaryCard[] = [
    {
      id: "total",
      label: "Total threats",
      value: metrics.total,
      description: "All detected events",
      icon: Activity,
      iconColor: "text-blue-400",
      iconBg: "bg-blue-500/15 border-blue-400/20",
      ring: "ring-blue-500/20",
      accent: "from-blue-500/15 to-transparent",
    },
    {
      id: "open",
      label: "Open / active",
      value: metrics.open,
      description: "Requires attention",
      icon: AlertTriangle,
      iconColor: "text-rose-400",
      iconBg: "bg-rose-500/15 border-rose-400/20",
      ring: "ring-rose-500/20",
      accent: "from-rose-500/15 to-transparent",
    },
    {
      id: "critical",
      label: "Critical",
      value: metrics.critical,
      description: `${metrics.high} high severity`,
      icon: ShieldAlert,
      iconColor: "text-purple-400",
      iconBg: "bg-purple-500/15 border-purple-400/20",
      ring: "ring-purple-500/20",
      accent: "from-purple-500/15 to-transparent",
    },
    {
      id: "quarantine",
      label: "Quarantined",
      value: metrics.quarantined,
      description: "Held for review",
      icon: FileWarning,
      iconColor: "text-amber-400",
      iconBg: "bg-amber-500/15 border-amber-400/20",
      ring: "ring-amber-500/20",
      accent: "from-amber-500/15 to-transparent",
    },
    {
      id: "resolved",
      label: "Resolved",
      value: metrics.resolved,
      description: `${metrics.resolutionRate}% resolution rate`,
      icon: CheckCircle2,
      iconColor: "text-emerald-400",
      iconBg: "bg-emerald-500/15 border-emerald-400/20",
      ring: "ring-emerald-500/20",
      accent: "from-emerald-500/15 to-transparent",
    },
    {
      id: "posture",
      label: "Security posture",
      value:
        metrics.critical > 0
          ? "Alert"
          : metrics.open > 3
            ? "Elevated"
            : "Secure",
      description:
        metrics.critical > 0
          ? "Critical threats open"
          : metrics.open > 3
            ? "Multiple open items"
            : "Within normal range",
      icon: ShieldCheck,
      iconColor:
        metrics.critical > 0
          ? "text-rose-400"
          : metrics.open > 3
            ? "text-amber-400"
            : "text-emerald-400",
      iconBg:
        metrics.critical > 0
          ? "bg-rose-500/15 border-rose-400/20"
          : metrics.open > 3
            ? "bg-amber-500/15 border-amber-400/20"
            : "bg-emerald-500/15 border-emerald-400/20",
      ring:
        metrics.critical > 0
          ? "ring-rose-500/20"
          : metrics.open > 3
            ? "ring-amber-500/20"
            : "ring-emerald-500/20",
      accent:
        metrics.critical > 0
          ? "from-rose-500/15 to-transparent"
          : metrics.open > 3
            ? "from-amber-500/15 to-transparent"
            : "from-emerald-500/15 to-transparent",
    },
  ];

  if (isLoading) {
    return (
      <section
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        aria-label="Threat summary loading"
      >
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-2xl border border-slate-700/60 bg-slate-900/60"
          />
        ))}
      </section>
    );
  }

  return (
    <section aria-labelledby="threat-summary-heading">
      {/* Section header */}
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-rose-400/20 bg-rose-500/15">
          <TrendingUp size={18} className="text-rose-400" aria-hidden="true" />
        </div>
        <div>
          <h3
            id="threat-summary-heading"
            className="text-base font-semibold text-slate-100"
          >
            Threat summary
          </h3>
          <p className="text-xs text-slate-500">
            Live posture across ingestion and scan pipeline
            {securityStats ? ` · ${securityStats.totalThreats} tracked` : ""}
          </p>
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => {
          const Icon = card.icon;
          const isPosture = card.id === "posture";

          return (
            <article
              key={card.id}
              className={`relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/80 to-slate-950/90 p-5 shadow-[0_8px_24px_rgba(0,0,0,0.3)] ring-1 backdrop-blur-xl ${card.ring}`}
            >
              <div
                className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${card.accent}`}
              />

              <div className="relative flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    {card.label}
                  </p>

                  <p
                    className={`mt-2 text-2xl font-bold tracking-tight ${
                      isPosture ? card.iconColor : "text-white"
                    }`}
                  >
                    {card.value}
                  </p>

                  <p className="mt-1.5 text-xs text-slate-500">
                    {card.description}
                  </p>
                </div>

                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border ${card.iconBg} ${card.iconColor}`}
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
};

export default ThreatSummary;