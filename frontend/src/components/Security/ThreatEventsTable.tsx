import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Eye,
  Search,
  Filter,
  X,
  Hash,
  Clock,
  FileText,
  ShieldAlert,
  Activity,
  CheckCircle2,
  CircleDot,
} from "lucide-react";

import { threatEvents } from "./data";
import type { ThreatEvent } from "./types";

/* ────────────────────────────────────────────────────────────────────────── */
/* Types                                                                      */
/* ────────────────────────────────────────────────────────────────────────── */

type SeverityFilter = "ALL" | "Critical" | "High" | "Medium" | "Low";
type StatusFilter = "ALL" | "Open" | "Investigating" | "Resolved" | "Quarantined";
type SortKey = "detectedAt" | "severity" | "fileName" | "status";

interface ThreatEventsTableProps {
  events?: ThreatEvent[];
  onView?: (event: ThreatEvent) => void;
  isLoading?: boolean;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Helpers                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

const SEVERITY_ORDER: Record<string, number> = {
  Critical: 0,
  High: 1,
  Medium: 2,
  Low: 3,
};

function severityClass(severity: string): string {
  const s = severity.toLowerCase();
  if (s === "critical") {
    return "bg-purple-500/15 text-purple-300 ring-1 ring-purple-500/30";
  }
  if (s === "high") {
    return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30";
  }
  if (s === "medium") {
    return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30";
  }
  return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
}

function statusClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "open") {
    return "bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/25";
  }
  if (s === "investigating") {
    return "bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/25";
  }
  if (s === "quarantined") {
    return "bg-orange-500/10 text-orange-300 ring-1 ring-orange-500/25";
  }
  if (s === "resolved") {
    return "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/25";
  }
  return "bg-slate-500/10 text-slate-400 ring-1 ring-slate-500/25";
}

function StatusIcon({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "resolved") {
    return <CheckCircle2 size={14} className="text-emerald-400" aria-hidden="true" />;
  }
  if (s === "investigating") {
    return <Activity size={14} className="text-amber-400" aria-hidden="true" />;
  }
  if (s === "quarantined") {
    return <ShieldAlert size={14} className="text-orange-400" aria-hidden="true" />;
  }
  return <CircleDot size={14} className="text-rose-400" aria-hidden="true" />;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Component                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

const ThreatEventsTable = ({
  events = threatEvents,
  onView,
  isLoading = false,
}: ThreatEventsTableProps) => {
  const [search, setSearch] = useState("");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("ALL");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("detectedAt");
  const [selected, setSelected] = useState<ThreatEvent | null>(null);

  const dialogRef = useRef<HTMLDialogElement>(null);

  const filteredEvents = useMemo(() => {
    const q = search.trim().toLowerCase();

    let result = events.filter((ev) => {
      if (severityFilter !== "ALL" && ev.severity !== severityFilter) {
        return false;
      }
      if (statusFilter !== "ALL" && ev.status !== statusFilter) {
        return false;
      }
      if (!q) return true;
      return (
        ev.fileName.toLowerCase().includes(q) ||
        ev.threatType.toLowerCase().includes(q) ||
        ev.id.toLowerCase().includes(q) ||
        ev.source.toLowerCase().includes(q) ||
        ev.status.toLowerCase().includes(q)
      );
    });

    result = [...result].sort((a, b) => {
      if (sortKey === "fileName") {
        return a.fileName.localeCompare(b.fileName);
      }
      if (sortKey === "severity") {
        return (
          (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
        );
      }
      if (sortKey === "status") {
        return a.status.localeCompare(b.status);
      }
      // detectedAt — keep original order (newest-first assumed in data)
      return 0;
    });

    return result;
  }, [events, search, severityFilter, statusFilter, sortKey]);

  const openCount = useMemo(
    () =>
      events.filter(
        (e) => e.status === "Open" || e.status === "Investigating"
      ).length,
    [events]
  );

  const criticalCount = useMemo(
    () => events.filter((e) => e.severity === "Critical").length,
    [events]
  );

  const openModal = useCallback(
    (event: ThreatEvent) => {
      setSelected(event);
      onView?.(event);
    },
    [onView]
  );

  const closeModal = useCallback(() => {
    setSelected(null);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (selected) {
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [selected]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => setSelected(null);
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  return (
    <>
      <section
        className="analytics-card"
        aria-labelledby="threat-events-heading"
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-rose-500/10 text-rose-400">
              <AlertTriangle size={20} aria-hidden="true" />
            </div>
            <div>
              <h3
                id="threat-events-heading"
                className="text-xl font-semibold text-slate-100"
              >
                Threat Events
              </h3>
              <p className="text-sm text-slate-400">
                Detected threats across uploads and APIs
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-rose-500/15 px-2.5 py-1 text-xs font-semibold text-rose-300 ring-1 ring-rose-500/30"
              aria-label={`${openCount} open threats`}
            >
              {openCount} Open
            </span>
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-purple-500/15 px-2.5 py-1 text-xs font-semibold text-purple-300 ring-1 ring-purple-500/30"
              aria-label={`${criticalCount} critical threats`}
            >
              {criticalCount} Critical
            </span>
            <span
              className="badge-warning inline-flex items-center gap-1.5"
              aria-label={`${events.length} total threat events`}
            >
              {events.length} Total
            </span>
          </div>
        </div>

        {/* ── Toolbar ────────────────────────────────────────────────── */}
        <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
              aria-hidden="true"
            />
            <label htmlFor="threat-search" className="sr-only">
              Search threat events
            </label>
            <input
              id="threat-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by file, type, ID, or source…"
              className="w-full rounded-lg border border-slate-700 bg-slate-900/60 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder:text-slate-500 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Filter size={16} className="text-slate-500" aria-hidden="true" />

            <label htmlFor="severity-filter" className="sr-only">
              Filter by severity
            </label>
            <select
              id="severity-filter"
              value={severityFilter}
              onChange={(e) =>
                setSeverityFilter(e.target.value as SeverityFilter)
              }
              className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="ALL">All severities</option>
              <option value="Critical">Critical</option>
              <option value="High">High</option>
              <option value="Medium">Medium</option>
              <option value="Low">Low</option>
            </select>

            <label htmlFor="status-filter" className="sr-only">
              Filter by status
            </label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="ALL">All statuses</option>
              <option value="Open">Open</option>
              <option value="Investigating">Investigating</option>
              <option value="Quarantined">Quarantined</option>
              <option value="Resolved">Resolved</option>
            </select>

            <label htmlFor="sort-key" className="sr-only">
              Sort events
            </label>
            <select
              id="sort-key"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="detectedAt">Sort by Time</option>
              <option value="severity">Sort by Severity</option>
              <option value="fileName">Sort by File</option>
              <option value="status">Sort by Status</option>
            </select>
          </div>
        </div>

        {/* ── Content ────────────────────────────────────────────────── */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-slate-400">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-rose-500" />
            <span className="ml-3 text-sm">Loading threat events…</span>
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 px-6 py-12 text-center">
            <AlertTriangle
              size={32}
              className="mx-auto mb-3 text-slate-600"
              aria-hidden="true"
            />
            <p className="text-sm font-medium text-slate-300">
              {search || severityFilter !== "ALL" || statusFilter !== "ALL"
                ? "No matching threat events"
                : "No threat events yet"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {search || severityFilter !== "ALL" || statusFilter !== "ALL"
                ? "Try adjusting your search or filters."
                : "Detected threats will appear here in real time."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left">
              <thead>
                <tr className="border-b border-slate-700/80 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  <th scope="col" className="px-4 py-3">
                    ID
                  </th>
                  <th scope="col" className="px-4 py-3">
                    File
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Threat type
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Severity
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Source
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Detected
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-sm">
                {filteredEvents.map((event) => (
                  <tr
                    key={event.id}
                    className="group transition-colors hover:bg-slate-800/50"
                  >
                    <td className="px-4 py-3.5 font-mono text-[11px] text-slate-500">
                      {event.id}
                    </td>
                    <td className="max-w-[160px] truncate px-4 py-3.5 font-medium text-slate-100">
                      {event.fileName}
                    </td>
                    <td className="px-4 py-3.5 text-slate-400">
                      {event.threatType}
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${severityClass(
                          event.severity
                        )}`}
                      >
                        {event.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-slate-400">
                      {event.source}
                    </td>
                    <td className="px-4 py-3.5">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${statusClass(
                          event.status
                        )}`}
                      >
                        <StatusIcon status={event.status} />
                        {event.status}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-right text-[11px] text-slate-500">
                      {event.detectedAt}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button
                        type="button"
                        onClick={() => openModal(event)}
                        className="btn-secondary inline-flex opacity-70 transition group-hover:opacity-100"
                        title="View threat details"
                        aria-label={`View details for ${event.id}`}
                      >
                        <Eye size={16} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Detail modal ───────────────────────────────────────────────── */}
      <dialog
        ref={dialogRef}
        className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-0 text-slate-100 shadow-2xl backdrop:bg-black/60"
        aria-labelledby="threat-modal-title"
      >
        {selected && (
          <div className="flex flex-col">
            <div className="flex items-start justify-between gap-4 border-b border-slate-700 px-6 py-4">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-rose-500/15 text-rose-400">
                  <AlertTriangle size={20} aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <h2
                    id="threat-modal-title"
                    className="truncate text-lg font-semibold text-slate-100"
                  >
                    {selected.id}
                  </h2>
                  <p className="mt-0.5 text-sm text-slate-400">
                    Threat event details
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
                aria-label="Close details"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="space-y-4 px-6 py-5">
              <DetailRow
                icon={<FileText size={16} />}
                label="File name"
                value={selected.fileName}
              />
              <DetailRow
                icon={<ShieldAlert size={16} />}
                label="Threat type"
                value={selected.threatType}
              />
              <DetailRow
                icon={<AlertTriangle size={16} />}
                label="Severity"
                value={selected.severity}
                valueClassName={
                  selected.severity === "Critical" || selected.severity === "High"
                    ? "text-rose-300"
                    : selected.severity === "Medium"
                      ? "text-amber-300"
                      : "text-emerald-300"
                }
              />
              <DetailRow
                icon={<Hash size={16} />}
                label="Source"
                value={selected.source}
              />
              <DetailRow
                icon={<Activity size={16} />}
                label="Status"
                value={selected.status}
              />
              <DetailRow
                icon={<Clock size={16} />}
                label="Detected at"
                value={selected.detectedAt}
              />
            </div>

            <div className="flex justify-end border-t border-slate-700 px-6 py-4">
              <button
                type="button"
                onClick={closeModal}
                className="btn-secondary"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </dialog>
    </>
  );
};

/* ── Detail row helper ──────────────────────────────────────────────────── */

interface DetailRowProps {
  icon: ReactNode;
  label: string;
  value: string;
  valueClassName?: string;
}

function DetailRow({ icon, label, value, valueClassName = "" }: DetailRowProps) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 text-slate-500" aria-hidden="true">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {label}
        </dt>
        <dd
          className={`mt-0.5 text-sm font-medium text-slate-200 ${valueClassName}`}
        >
          {value}
        </dd>
      </div>
    </div>
  );
}

export default ThreatEventsTable;