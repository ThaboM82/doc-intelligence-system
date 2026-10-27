import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Eye,
  Trash2,
  Download,
  ShieldAlert,
  Search,
  Filter,
  X,
  FileWarning,
  Calendar,
  HardDrive,
  Hash,
  AlertTriangle,
  Moon,
  Sun,
} from "lucide-react";

import { quarantinedFiles } from "./data";
import type { QuarantinedFile } from "./types";

type SortKey = "date" | "fileName" | "size";
type Theme = "dark" | "light";

interface QuarantineTableProps {
  files?: QuarantinedFile[];
  onView?: (file: QuarantinedFile) => void;
  onDownload?: (file: QuarantinedFile) => void;
  onDelete?: (file: QuarantinedFile) => void;
  isLoading?: boolean;
}

const QuarantineTable = ({
  files = quarantinedFiles,
  onView,
  onDownload,
  onDelete,
  isLoading = false,
}: QuarantineTableProps) => {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [selectedFile, setSelectedFile] = useState<QuarantinedFile | null>(
    null
  );
  const [theme, setTheme] = useState<Theme>("dark");

  const dialogRef = useRef<HTMLDialogElement>(null);
  const isDark = theme === "dark";

  const filteredFiles = useMemo(() => {
    const query = search.trim().toLowerCase();
    let result = files;

    if (query) {
      result = result.filter(
        (file) =>
          file.fileName.toLowerCase().includes(query) ||
          file.reason.toLowerCase().includes(query) ||
          file.id.toLowerCase().includes(query)
      );
    }

    return [...result].sort((a, b) => {
      if (sortKey === "fileName") {
        return a.fileName.localeCompare(b.fileName);
      }
      if (sortKey === "size") {
        return a.size.localeCompare(b.size, undefined, { numeric: true });
      }
      return b.date.localeCompare(a.date);
    });
  }, [files, search, sortKey]);

  const openModal = useCallback(
    (file: QuarantinedFile) => {
      setSelectedFile(file);
      onView?.(file);
    },
    [onView]
  );

  const closeModal = useCallback(() => {
    setSelectedFile(null);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  // Keep native <dialog> in sync with selectedFile
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (selectedFile) {
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [selectedFile]);

  // Reset state when dialog is closed via Escape or backdrop
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleClose = () => setSelectedFile(null);
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  const handleDownload = useCallback(
    (file: QuarantinedFile) => {
      onDownload?.(file);
    },
    [onDownload]
  );

  const handleDelete = useCallback(
    (file: QuarantinedFile) => {
      const confirmed = window.confirm(
        `Permanently delete quarantined file "${file.fileName}"?\n\nThis action cannot be undone.`
      );

      if (!confirmed) return;

      onDelete?.(file);

      if (selectedFile?.id === file.id) {
        closeModal();
      }
    },
    [onDelete, selectedFile, closeModal]
  );

  // Theme-aware class helpers
  const cardClass = isDark
    ? "analytics-card bg-slate-900 border-slate-700"
    : "analytics-card bg-white border-slate-200 shadow-sm";

  const textPrimary = isDark ? "text-slate-100" : "text-slate-900";
  const textSecondary = isDark ? "text-slate-400" : "text-slate-500";
  const textMuted = isDark ? "text-slate-500" : "text-slate-400";
  const inputClass = isDark
    ? "border-slate-700 bg-slate-900/60 text-slate-200 placeholder:text-slate-500 focus:border-slate-500 focus:ring-slate-500"
    : "border-slate-300 bg-white text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:ring-slate-400";

  const rowClass = isDark
    ? "document-card group flex flex-col gap-4 sm:flex-row sm:items-center transition-all duration-200 hover:bg-slate-800/80 hover:border-slate-600 hover:shadow-md hover:shadow-black/20"
    : "document-card group flex flex-col gap-4 sm:flex-row sm:items-center transition-all duration-200 hover:bg-slate-50 hover:border-slate-300 hover:shadow-md";

  const modalClass = isDark
    ? "w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-0 text-slate-100 shadow-2xl backdrop:bg-black/60"
    : "w-full max-w-lg rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-black/40";

  return (
    <>
      <section
        className={cardClass}
        aria-labelledby="quarantine-heading"
        data-theme={theme}
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                isDark
                  ? "bg-amber-500/10 text-amber-500"
                  : "bg-amber-100 text-amber-600"
              }`}
            >
              <ShieldAlert size={20} aria-hidden="true" />
            </div>
            <div>
              <h3
                id="quarantine-heading"
                className={`text-xl font-semibold ${textPrimary}`}
              >
                Quarantine
              </h3>
              <p className={`text-sm ${textSecondary}`}>
                Files held for security review
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 self-start sm:self-auto">
            {/* Dark mode toggle */}
            <button
              type="button"
              onClick={toggleTheme}
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                isDark
                  ? "border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700"
                  : "border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            >
              {isDark ? (
                <Sun size={16} aria-hidden="true" />
              ) : (
                <Moon size={16} aria-hidden="true" />
              )}
              <span className="hidden sm:inline">
                {isDark ? "Light" : "Dark"}
              </span>
            </button>

            <span
              className="badge-warning inline-flex items-center gap-1.5"
              aria-label={`${files.length} files in quarantine`}
            >
              {files.length} {files.length === 1 ? "File" : "Files"}
            </span>
          </div>
        </div>

        {/* ── Toolbar ────────────────────────────────────────────────── */}
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              size={16}
              className={`pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 ${textMuted}`}
              aria-hidden="true"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, reason, or ID…"
              className={`w-full rounded-lg border py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-1 ${inputClass}`}
              aria-label="Search quarantined files"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter size={16} className={textMuted} aria-hidden="true" />
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className={`rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-1 ${inputClass}`}
              aria-label="Sort quarantined files"
            >
              <option value="date">Sort by Date</option>
              <option value="fileName">Sort by Name</option>
              <option value="size">Sort by Size</option>
            </select>
          </div>
        </div>

        {/* ── Content ────────────────────────────────────────────────── */}
        {isLoading ? (
          <div
            className={`flex items-center justify-center py-12 ${textSecondary}`}
          >
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-amber-500" />
            <span className="ml-3 text-sm">Loading quarantine…</span>
          </div>
        ) : filteredFiles.length === 0 ? (
          <div
            className={`rounded-lg border border-dashed px-6 py-12 text-center ${
              isDark
                ? "border-slate-700 bg-slate-900/40"
                : "border-slate-300 bg-slate-50"
            }`}
          >
            <ShieldAlert
              size={32}
              className={`mx-auto mb-3 ${textMuted}`}
              aria-hidden="true"
            />
            <p className={`text-sm font-medium ${textPrimary}`}>
              {search ? "No matching files" : "Quarantine is empty"}
            </p>
            <p className={`mt-1 text-xs ${textMuted}`}>
              {search
                ? "Try a different search term."
                : "Suspicious uploads will appear here for review."}
            </p>
          </div>
        ) : (
          <ul className="space-y-3" role="list">
            {filteredFiles.map((file) => (
              <li key={file.id} className={rowClass}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4
                      className={`truncate font-semibold ${textPrimary} transition-colors group-hover:${
                        isDark ? "text-white" : "text-slate-900"
                      }`}
                    >
                      {file.fileName}
                    </h4>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                        isDark
                          ? "bg-slate-800 text-slate-400"
                          : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      {file.id}
                    </span>
                  </div>

                  <p
                    className={`mt-1 text-sm ${
                      isDark ? "text-amber-400/90" : "text-amber-600"
                    }`}
                  >
                    {file.reason}
                  </p>

                  <p className={`mt-1 text-xs ${textMuted}`}>
                    {file.date}
                    <span className="mx-1.5 opacity-60">•</span>
                    {file.size}
                  </p>
                </div>

                <div className="flex shrink-0 gap-2 opacity-80 transition-opacity group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={() => openModal(file)}
                    className="btn-secondary"
                    title="View details"
                    aria-label={`View details for ${file.fileName}`}
                  >
                    <Eye size={18} aria-hidden="true" />
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDownload(file)}
                    className="btn-secondary"
                    title="Download for analysis"
                    aria-label={`Download ${file.fileName}`}
                  >
                    <Download size={18} aria-hidden="true" />
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDelete(file)}
                    className="btn-danger"
                    title="Permanently delete"
                    aria-label={`Delete ${file.fileName}`}
                  >
                    <Trash2 size={18} aria-hidden="true" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── File Details Modal ───────────────────────────────────────── */}
      <dialog
        ref={dialogRef}
        className={modalClass}
        aria-labelledby="quarantine-modal-title"
      >
        {selectedFile && (
          <div className="flex flex-col">
            {/* Modal header */}
            <div
              className={`flex items-start justify-between gap-4 border-b px-6 py-4 ${
                isDark ? "border-slate-700" : "border-slate-200"
              }`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                    isDark
                      ? "bg-amber-500/15 text-amber-400"
                      : "bg-amber-100 text-amber-600"
                  }`}
                >
                  <FileWarning size={20} aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <h2
                    id="quarantine-modal-title"
                    className={`truncate text-lg font-semibold ${textPrimary}`}
                  >
                    {selectedFile.fileName}
                  </h2>
                  <p className={`mt-0.5 text-sm ${textSecondary}`}>
                    Quarantine details
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={closeModal}
                className={`rounded-lg p-1.5 transition ${
                  isDark
                    ? "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                }`}
                aria-label="Close details"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            {/* Modal body */}
            <div className="space-y-4 px-6 py-5">
              <DetailRow
                icon={<Hash size={16} />}
                label="Quarantine ID"
                value={selectedFile.id}
                isDark={isDark}
              />
              <DetailRow
                icon={<AlertTriangle size={16} />}
                label="Reason"
                value={selectedFile.reason}
                valueClassName={isDark ? "text-amber-400" : "text-amber-600"}
                isDark={isDark}
              />
              <DetailRow
                icon={<Calendar size={16} />}
                label="Quarantined on"
                value={selectedFile.date}
                isDark={isDark}
              />
              <DetailRow
                icon={<HardDrive size={16} />}
                label="File size"
                value={selectedFile.size}
                isDark={isDark}
              />

              <div
                className={`rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/20 bg-amber-500/5 text-amber-200/90"
                    : "border-amber-200 bg-amber-50 text-amber-800"
                }`}
              >
                <p className="font-medium">Security notice</p>
                <p
                  className={`mt-1 text-xs ${
                    isDark ? "text-amber-200/70" : "text-amber-700/80"
                  }`}
                >
                  This file was blocked by the security scanner and is held in
                  quarantine. Download only in a controlled environment.
                  Permanent deletion cannot be undone.
                </p>
              </div>
            </div>

            {/* Modal footer */}
            <div
              className={`flex flex-col-reverse gap-2 border-t px-6 py-4 sm:flex-row sm:justify-end ${
                isDark ? "border-slate-700" : "border-slate-200"
              }`}
            >
              <button
                type="button"
                onClick={closeModal}
                className="btn-secondary"
              >
                Close
              </button>

              <button
                type="button"
                onClick={() => handleDownload(selectedFile)}
                className="btn-secondary inline-flex items-center justify-center gap-2"
              >
                <Download size={16} aria-hidden="true" />
                Download
              </button>

              <button
                type="button"
                onClick={() => handleDelete(selectedFile)}
                className="btn-danger inline-flex items-center justify-center gap-2"
              >
                <Trash2 size={16} aria-hidden="true" />
                Delete
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
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClassName?: string;
  isDark?: boolean;
}

function DetailRow({
  icon,
  label,
  value,
  valueClassName = "",
  isDark = true,
}: DetailRowProps) {
  return (
    <div className="flex items-start gap-3">
      <div
        className={`mt-0.5 ${isDark ? "text-slate-500" : "text-slate-400"}`}
        aria-hidden="true"
      >
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <dt
          className={`text-xs font-medium uppercase tracking-wide ${
            isDark ? "text-slate-500" : "text-slate-400"
          }`}
        >
          {label}
        </dt>
        <dd
          className={`mt-0.5 text-sm font-medium ${
            valueClassName || (isDark ? "text-slate-200" : "text-slate-800")
          }`}
        >
          {value}
        </dd>
      </div>
    </div>
  );
}

export default QuarantineTable;