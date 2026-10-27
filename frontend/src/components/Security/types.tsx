/**
 * Shared Security domain types.
 * Used by ThreatEventsTable, QuarantineTable, ThreatSummary, SecurityDashboard.
 */

/* ────────────────────────────────────────────────────────────────────────── */
/* Severity & status                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/** Threat / event severity levels (ordered from highest to lowest impact). */
export type Severity = "Critical" | "High" | "Medium" | "Low";

/** Lifecycle status for a detected threat event. */
export type ThreatStatus =
  | "Open"
  | "Investigating"
  | "Quarantined"
  | "Resolved";

/** Source channel where the file or event originated. */
export type ThreatSource =
  | "Email Upload"
  | "Web Portal"
  | "REST API"
  | "Admin Upload"
  | string;

/* ────────────────────────────────────────────────────────────────────────── */
/* Core entities                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * A single detected threat event from the security / ingestion pipeline.
 */
export interface ThreatEvent {
  /** Stable unique identifier (e.g. TH-001). */
  id: string;
  /** Original file name as uploaded. */
  fileName: string;
  /** Classifier label (e.g. Macro Malware, Prompt Injection). */
  threatType: string;
  severity: Severity;
  /** Ingestion channel or system that reported the event. */
  source: ThreatSource;
  /**
   * Detection time.
   * Prefer ISO-8601 in production; relative strings (e.g. "10:15") are allowed for mock UI.
   */
  detectedAt: string;
  status: ThreatStatus;
  /** Optional document / chunk ID in the vector store. */
  documentId?: string;
  /** Optional scanner or detector name. */
  detector?: string;
  /** Optional confidence / risk score 0–1. */
  riskScore?: number;
  /** Optional free-text detail from the scanner. */
  detail?: string;
}

/**
 * A file held in quarantine after failing a security scan.
 */
export interface QuarantinedFile {
  /** Stable unique identifier (e.g. Q-001). */
  id: string;
  /** Original file name. */
  fileName: string;
  /** Human-readable reason for quarantine. */
  reason: string;
  /** Display size (e.g. "3.2 MB"). */
  size: string;
  /**
   * Quarantine date.
   * Prefer ISO-8601 (YYYY-MM-DD) in production.
   */
  date: string;
  /** Optional link back to the originating threat event. */
  threatEventId?: string;
  /** Optional severity of the underlying finding. */
  severity?: Severity;
  /** Optional storage path or object key in quarantine store. */
  storageKey?: string;
}

/**
 * Aggregate metric card for summary / dashboard views.
 */
export interface SecurityMetric {
  /** Display title (e.g. "Open threats"). */
  title: string;
  /** Primary numeric value. */
  value: number;
  /**
   * Short trend label (e.g. "+12%", "−3", "stable").
   * Prefer structured trend fields in API responses when available.
   */
  trend: string;
  /** Optional unit or suffix (e.g. "%", "files"). */
  unit?: string;
  /** Optional secondary description. */
  description?: string;
}

/**
 * Pre-computed summary stats for threat / quarantine views.
 */
export interface SecurityStats {
  totalThreats: number;
  openThreats: number;
  criticalThreats: number;
  quarantinedCount: number;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Filters & UI helpers                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

export type SeverityFilter = "ALL" | Severity;
export type ThreatStatusFilter = "ALL" | ThreatStatus;

export type ThreatSortKey =
  | "detectedAt"
  | "severity"
  | "fileName"
  | "status";

export type QuarantineSortKey = "date" | "fileName" | "size";

/* ────────────────────────────────────────────────────────────────────────── */
/* Type guards (runtime-safe narrowings)                                      */
/* ────────────────────────────────────────────────────────────────────────── */

const SEVERITIES: readonly Severity[] = [
  "Critical",
  "High",
  "Medium",
  "Low",
] as const;

const THREAT_STATUSES: readonly ThreatStatus[] = [
  "Open",
  "Investigating",
  "Quarantined",
  "Resolved",
] as const;

export function isSeverity(value: unknown): value is Severity {
  return (
    typeof value === "string" &&
    (SEVERITIES as readonly string[]).includes(value)
  );
}

export function isThreatStatus(value: unknown): value is ThreatStatus {
  return (
    typeof value === "string" &&
    (THREAT_STATUSES as readonly string[]).includes(value)
  );
}

/** Normalize arbitrary severity strings from APIs into the canonical union. */
export function normalizeSeverity(value: unknown): Severity {
  const s = String(value ?? "low").toLowerCase();
  if (s === "critical") return "Critical";
  if (s === "high") return "High";
  if (s === "medium") return "Medium";
  return "Low";
}

/** Normalize arbitrary status strings from APIs into the canonical union. */
export function normalizeThreatStatus(value: unknown): ThreatStatus {
  const s = String(value ?? "open").toLowerCase();
  if (s === "investigating" || s === "in_progress") return "Investigating";
  if (s === "quarantined" || s === "quarantine") return "Quarantined";
  if (s === "resolved" || s === "closed" || s === "done") return "Resolved";
  return "Open";
}