import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

type AuditEvent = {
  id: string;
  actor?: string;
  action: string;
  resource?: string;
  createdAt: string;
  severity?: "low" | "medium" | "high" | "critical";
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function formatDate(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function severityColor(severity?: AuditEvent["severity"]) {
  switch (severity) {
    case "critical":
      return "text-red-700 bg-red-50 border-red-200";
    case "high":
      return "text-orange-700 bg-orange-50 border-orange-200";
    case "medium":
      return "text-yellow-700 bg-yellow-50 border-yellow-200";
    case "low":
      return "text-green-700 bg-green-50 border-green-200";
    default:
      return "text-slate-700 bg-slate-50 border-slate-200";
  }
}

export default function Audit() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<AuditEvent["severity"] | "all">("all");
  const [minDate, setMinDate] = useState<string>("");

  useEffect(() => {
    let alive = true;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const res = await fetch(`${API_BASE_URL}/audit/events`, {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
        });

        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `Audit fetch failed (${res.status})`);
        }

        const data = (await res.json()) as { events?: AuditEvent[]; data?: AuditEvent[] };

        if (!alive) return;
        setEvents(data.events ?? data.data ?? []);
      } catch (e: any) {
        if (!alive) return;
        setError(e?.message ?? "Failed to load audit events.");
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    }

    load();
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    return events
      .filter((ev) => {
        if (severity !== "all" && ev.severity !== severity) return false;
        if (minDate) {
          const t = new Date(minDate).getTime();
          if (!Number.isNaN(t)) {
            if (new Date(ev.createdAt).getTime() < t) return false;
          }
        }
        if (!q) return true;

        const hay = [
          ev.actor,
          ev.action,
          ev.resource,
          ev.severity,
          ev.createdAt,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();

        return hay.includes(q);
      })
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [events, query, severity, minDate]);

  return (
    <main className="p-4 md:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Audit Logs</h1>
          <p className="text-slate-600 mt-1">
            Track security-relevant actions across the system.
          </p>
        </div>

        <Link
          to="/settings"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50"
        >
          Manage Settings
        </Link>
      </div>

      <section className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="md:col-span-2">
          <label className="text-sm font-medium text-slate-700">Search</label>
          <input
            className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2"
            placeholder="Search by actor, action, resource..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search audit logs"
          />
        </div>

        <div>
          <label className="text-sm font-medium text-slate-700">Severity</label>
          <select
            className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 bg-white"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as any)}
            aria-label="Filter by severity"
          >
            <option value="all">All</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </div>

        <div>
          <label className="text-sm font-medium text-slate-700">From date</label>
          <input
            type="date"
            className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 bg-white"
            value={minDate}
            onChange={(e) => setMinDate(e.target.value)}
            aria-label="Filter by from date"
          />
        </div>
      </section>

      <section className="mt-6 rounded-lg border border-slate-200 overflow-hidden">
        <div className="bg-slate-50 px-4 py-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">Events</h2>
          <span className="text-sm text-slate-600">
            {filtered.length} result{filtered.length === 1 ? "" : "s"}
          </span>
        </div>

        {loading ? (
          <div className="p-6 text-slate-600">Loading audit events…</div>
        ) : error ? (
          <div className="p-6 text-red-700">
            <div className="font-medium">Unable to load audit logs</div>
            <div className="mt-2 text-sm opacity-90">{error}</div>
          </div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-left">
              <thead className="bg-white border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Time</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Actor</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Action</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Resource</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Severity</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-slate-600">
                      No audit events found.
                    </td>
                  </tr>
                ) : (
                  filtered.map((ev) => (
                    <tr key={ev.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3 text-sm text-slate-700">{formatDate(ev.createdAt)}</td>
                      <td className="px-4 py-3 text-sm text-slate-700">{ev.actor ?? "—"}</td>
                      <td className="px-4 py-3 text-sm font-medium text-slate-900">{ev.action}</td>
                      <td className="px-4 py-3 text-sm text-slate-700">{ev.resource ?? "—"}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${severityColor(
                            ev.severity
                          )}`}
                        >
                          {ev.severity ?? "unknown"}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="mt-4 text-xs text-slate-500">
        Tip: This page expects an <code className="px-1 py-0.5 bg-slate-100 rounded">GET /audit/events</code> endpoint.
        Update API paths as needed.
      </p>
    </main>
  );
}