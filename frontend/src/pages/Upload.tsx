import React, { useMemo, useRef, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type UploadResponse = {
  id?: string;
  filename?: string;
  status?: "queued" | "processing" | "completed" | "quarantined" | "rejected";
  message?: string;
};

function bytesToMb(bytes: number) {
  return bytes / (1024 * 1024);
}

export default function Upload() {
  const fileRef = useRef<HTMLInputElement | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewName, setPreviewName] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);

  const maxSizeMb = 50; // You can replace with backend-driven value from settings.

  const fileInfo = useMemo(() => {
    if (!file) return null;
    return {
      name: file.name,
      sizeMb: bytesToMb(file.size),
      type: file.type || "unknown",
    };
  }, [file]);

  function pickFile(f: File | null) {
    setError(null);
    setResult(null);

    if (!f) {
      setFile(null);
      setPreviewName("");
      return;
    }

    const sizeMb = bytesToMb(f.size);
    if (sizeMb > maxSizeMb) {
      setError(`File is too large (${sizeMb.toFixed(2)} MB). Max allowed is ${maxSizeMb} MB.`);
      setFile(null);
      setPreviewName("");
      return;
    }

    setFile(f);
    setPreviewName(f.name);
  }

  async function submit() {
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);

    try {
      const form = new FormData();
      form.append("file", file);

      const res = await fetch(`${API_BASE_URL}/upload/scan`, {
        method: "POST",
        credentials: "include",
        body: form,
      });

      const text = await res.text().catch(() => "");
      let data: any = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { message: text || undefined };
      }

      if (!res.ok) {
        throw new Error(data?.message ?? text || `Upload failed (${res.status})`);
      }

      setResult((data ?? {}) as UploadResponse);
      setFile(null);
      setPreviewName("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (e: any) {
      setError(e?.message ?? "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="p-4 md:p-6 max-w-3xl">
      <h1 className="text-2xl font-semibold">Upload</h1>
      <p className="text-slate-600 mt-1">Upload a document for security scanning.</p>

      <section className="mt-6 rounded-lg border border-slate-200 overflow-hidden">
        <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold text-slate-800">Scan Upload</h2>
        </div>

        <div className="p-4 space-y-4">
          {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-800 text-sm">{error}</div>}

          {result && (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-slate-900 text-sm">
              <div className="font-semibold">Result</div>
              <div className="mt-1 text-slate-700">
                {result.message ?? "Upload processed."}
              </div>
              {result.status && <div className="mt-1 text-xs text-slate-600">Status: {result.status}</div>}
            </div>
          )}

          <div
            className="rounded-md border border-dashed border-slate-300 p-5 bg-white"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0] ?? null;
              pickFile(f);
            }}
          >
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div>
                <div className="text-sm font-semibold text-slate-900">Drag & drop or choose a file</div>
                <div className="text-xs text-slate-600 mt-1">
                  Max {maxSizeMb} MB. Supported types depend on your backend.
                </div>
              </div>
              <button
                className="rounded-md bg-slate-900 text-white px-4 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-60"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
              >
                Choose File
              </button>
            </div>

            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />

            {previewName && (
              <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                <div className="font-semibold">{previewName}</div>
                {fileInfo && (
                  <div className="text-xs text-slate-600 mt-1">
                    {fileInfo.type} • {fileInfo.sizeMb.toFixed(2)} MB
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2">
            <button
              className="rounded-md border border-slate-200 px-4 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-60"
              onClick={() => pickFile(null)}
              disabled={uploading || !file}
            >
              Clear
            </button>

            <button
              className="rounded-md bg-slate-900 text-white px-4 py-2 text-sm font-semibold hover:bg-slate-800 disabled:opacity-60"
              onClick={submit}
              disabled={!file || uploading}
            >
              {uploading ? "Uploading…" : "Upload & Scan"}
            </button>
          </div>

          <div className="text-xs text-slate-500">
            Expected endpoint: <code>/upload/scan</code> (multipart/form-data).
          </div>
        </div>
      </section>
    </main>
  );
}