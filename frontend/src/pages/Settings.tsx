import React, { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type SecuritySettings = {
  enforceScan?: boolean;
  quarantineOnDetection?: boolean;
  maxUploadSizeMb?: number;
  allowedMimeTypes?: string[];
};

export default function Settings() {
  const [settings, setSettings] = useState<SecuritySettings>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/settings/security`, {
        method: "GET",
        credentials: "include",
      });
      if (!res.ok) throw new Error(`Failed to load settings (${res.status})`);

      const data = (await res.json()) as { settings?: SecuritySettings; data?: SecuritySettings };
      setSettings(data.settings ?? data.data ?? {});
    } catch (e: any) {
      setError(e?.message ?? "Unable to load settings.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const res = await fetch(`${API_BASE_URL}/settings/security`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `Save failed (${res.status})`);
      }

      setSuccess("Settings saved successfully.");
      await load();
    } catch (e: any) {
      setError(e?.message ?? "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="p-4 md:p-6 max-w-3xl">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <p className="text-slate-600 mt-1">Configure scanning and security policies.</p>

      <section className="mt-6 rounded-lg border border-slate-200 overflow-hidden">
        <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold text-slate-800">Security Settings</h2>
        </div>

        {loading ? (
          <div className="p-6 text-slate-600">Loading settings…</div>
        ) : (
          <div className="p-4 space-y-4">
            {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-800 text-sm">{error}</div>}
            {success && <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-green-800 text-sm">{success}</div>}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="rounded-md border border-slate-200 p-4 flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={!!settings.enforceScan}
                  onChange={(e) => setSettings((s) => ({ ...s, enforceScan: e.target.checked }))}
                />
                <div>
                  <div className="font-semibold text-slate-900 text-sm">Enforce Scan</div>
                  <div className="text-xs text-slate-600">Block or quarantine when threats are detected.</div>
                </div>
              </label>

              <label className="rounded-md border border-slate-200 p-4 flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={!!settings.quarantineOnDetection}
                  onChange={(e) => setSettings((s) => ({ ...s, quarantineOnDetection: e.target.checked }))}
                />
                <div>
                  <div className="font-semibold text-slate-900 text-sm">Quarantine on Detection</div>
                  <div className="text-xs text-slate-600">Move suspicious uploads to quarantine.</div>
                </div>
              </label>
            </div>

            <div>
              <label className="text-sm font-medium text-slate-700">Max Upload Size (MB)</label>
              <input
                type="number"
                min={1}
                className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2"
                value={settings.maxUploadSizeMb ?? ""}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    maxUploadSizeMb: e.target.value === "" ? undefined : Number(e.target.value),
                  }))
                }
              />
            </div>

            <div>
              <label className="text-sm font-medium text-slate-700">Allowed MIME Types</label>
              <input
                className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2"
                placeholder="e.g. application/pdf,image/png,text/plain"
                value={(settings.allowedMimeTypes ?? []).join(",")}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    allowedMimeTypes: e.target.value
                      .split(",")
                      .map((x) => x.trim())
                      .filter(Boolean),
                  }))
                }
              />
              <div className="mt-1 text-xs text-slate-500">
                Comma-separated list.
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                className="rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold hover:bg-slate-50"
                onClick={load}
                disabled={saving}
              >
                Reset
              </button>
              <button
                className="rounded-md bg-slate-900 text-white px-4 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-60"
                onClick={save}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}