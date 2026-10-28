import React, { useEffect, useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type QuarantinedItem = {
  id: string;
  filename: string;
  reason: string;
  severity?: "low" | "medium" | "high" | "critical";
  quarantinedAt: string;
};

function severityColor(sev?: QuarantinedItem["severity"]) {
  switch (sev) {
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

export default function Quarantine() {
  const [items, setItems] = useState<QuarantinedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/quarantine/items`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Fetch failed (${res.status})`);
      const data = (await res.json()) as { items?: QuarantinedItem[]; data?: QuarantinedItem[] };
      setItems(data.items ?? data.data ?? []);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load quarantine items.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) =>
      [it.filename, it.reason, it.severity, it.quarantinedAt].filter(Boolean).join(" ").toLowerCase().includes(q)
    );
  }, [items, query]);

  async function action(itemId: string, endpoint: string) {
    setBusyId(itemId);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ id: itemId }),
      });
      if (!res.ok) throw new Error(await res.text().catch(() => `Failed (${res.status})`));
      await refresh();
    } catch (e: any) {
      setError(e?.message ?? "Action failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">Quarantine</h1>
      <p className="text-slate-600 mt-1">Manage suspicious uploads safely.</p>

      <section className="mt-6 flex flex-col md:flex-row md:items-end gap-3 md:gap-4">
        <div className="md:flex-1">
          <label className="text-sm font-medium text-slate-700">Search</label>
          <input
            className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2"
            placeholder="Search by filename or reason…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </section>

      <section className="mt-6 rounded-lg border border-slate-200 overflow-hidden">
        <div className="bg-slate-50 px-4 py-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">Items</h2>
          <span className="text-sm text-slate-600">{filtered.length} found</span>
        </div>

        {loading ? (
          <div className="p-6 text-slate-600">Loading…</div>
        ) : error ? (
          <div className="p-6 text-red-700">
            <div className="font-medium">Unable to load quarantine</div>
            <div className="mt-2 text-sm opacity-90">{error}</div>
          </div>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-left">
              <thead className="bg-white border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Filename</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Reason</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Severity</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Quarantined</th>
                  <th className="px-4 py-3 text-sm font-semibold text-slate-700">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-slate-600">
                      No quarantined items match your filters.
                    </td>
                  </tr>
                ) : (
                  filtered.map((it) => (
                    <tr key={it.id} className="border-b border-slate-100 hover:bg-slate-50">
                      <td className="px-4 py-3 text-sm font-medium text-slate-900">{it.filename}</td>
                      <td className="px-4 py-3 text-sm text-slate-700">{it.reason}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${severityColor(
                            it.severity
                          )}`}
                        >
                          {it.severity ?? "unknown"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-700">
                        {new Date(it.quarantinedAt).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex gap-2">
                          <button
                            className="rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50 disabled:opacity-60"
                            disabled={busyId === it.id}
                            onClick={() => action(it.id, "/quarantine/restore")}
                            title="Restore item back to system"
                          >
                            Restore
                          </button>
                          <button
                            className="rounded-md bg-red-600 text-white px-3 py-2 hover:bg-red-700 disabled:opacity-60"
                            disabled={busyId === it.id}
                            onClick={() => action(it.id, "/quarantine/delete")}
                            title="Delete item permanently"
                          >
                            Delete
                          </button>
                        </div>
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
        Expected endpoints: <code>GET /quarantine/items</code>, <code>POST /quarantine/restore</code>, <code>POST /quarantine/delete</code>.
      </p>
    </main>
  );
}