import React, { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Shield,
  FileWarning,
  Archive,
  Image,
  Copy,
  HardDrive,
} from "lucide-react";

export type ValidationSeverity =
  | "success"
  | "warning"
  | "error";

export interface ValidationIssue {
  type:
    | "duplicate"
    | "file-size"
    | "file-type"
    | "zip-validation"
    | "image-validation"
    | "security"
    | "compliance";

  severity: ValidationSeverity;
  message: string;
}

export interface FileValidationResult {
  id: string;
  fileName: string;
  fileSize: number;
  valid: boolean;

  issues: ValidationIssue[];
}

interface FileValidationProps {
  results: FileValidationResult[];
  className?: string;
}

const formatFileSize = (
  bytes: number
): string => {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(2)} KB`;
  }

  if (bytes < 1024 * 1024 * 1024) {
    return `${(
      bytes /
      (1024 * 1024)
    ).toFixed(2)} MB`;
  }

  return `${(
    bytes /
    (1024 * 1024 * 1024)
  ).toFixed(2)} GB`;
};

const FileValidation: React.FC<
  FileValidationProps
> = ({
  results,
  className = "",
}) => {
  const summary = useMemo(() => {
    const total = results.length;

    const valid = results.filter(
      (file) => file.valid
    ).length;

    const invalid = total - valid;

    const warnings = results.reduce(
      (count, file) =>
        count +
        file.issues.filter(
          (issue) =>
            issue.severity ===
            "warning"
        ).length,
      0
    );

    const errors = results.reduce(
      (count, file) =>
        count +
        file.issues.filter(
          (issue) =>
            issue.severity === "error"
        ).length,
      0
    );

    return {
      total,
      valid,
      invalid,
      warnings,
      errors,
    };
  }, [results]);

  const getSeverityColor = (
    severity: ValidationSeverity
  ) => {
    switch (severity) {
      case "success":
        return "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";

      case "warning":
        return "border-amber-500/30 bg-amber-500/10 text-amber-400";

      case "error":
        return "border-red-500/30 bg-red-500/10 text-red-400";

      default:
        return "border-slate-700 bg-slate-800 text-slate-300";
    }
  };

  const getIssueIcon = (
    type: ValidationIssue["type"]
  ) => {
    switch (type) {
      case "duplicate":
        return (
          <Copy className="h-4 w-4" />
        );

      case "zip-validation":
        return (
          <Archive className="h-4 w-4" />
        );

      case "image-validation":
        return (
          <Image className="h-4 w-4" />
        );

      case "security":
        return (
          <Shield className="h-4 w-4" />
        );

      case "file-size":
        return (
          <HardDrive className="h-4 w-4" />
        );

      default:
        return (
          <FileWarning className="h-4 w-4" />
        );
    }
  };

  if (results.length === 0) {
    return (
      <div
        className={`rounded-xl border border-slate-800 bg-slate-900 p-6 ${className}`}
      >
        <div className="text-center text-slate-400">
          No files available for validation.
        </div>
      </div>
    );
  }

  return (
    <div
      className={`space-y-6 ${className}`}
    >
      {/* Summary */}

      <div className="grid gap-4 md:grid-cols-5">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase text-slate-500">
            Total Files
          </p>

          <p className="mt-2 text-2xl font-bold text-white">
            {summary.total}
          </p>
        </div>

        <div className="rounded-xl border border-emerald-800 bg-slate-900 p-4">
          <p className="text-xs uppercase text-slate-500">
            Valid
          </p>

          <p className="mt-2 text-2xl font-bold text-emerald-400">
            {summary.valid}
          </p>
        </div>

        <div className="rounded-xl border border-red-800 bg-slate-900 p-4">
          <p className="text-xs uppercase text-slate-500">
            Invalid
          </p>

          <p className="mt-2 text-2xl font-bold text-red-400">
            {summary.invalid}
          </p>
        </div>

        <div className="rounded-xl border border-amber-800 bg-slate-900 p-4">
          <p className="text-xs uppercase text-slate-500">
            Warnings
          </p>

          <p className="mt-2 text-2xl font-bold text-amber-400">
            {summary.warnings}
          </p>
        </div>

        <div className="rounded-xl border border-red-800 bg-slate-900 p-4">
          <p className="text-xs uppercase text-slate-500">
            Errors
          </p>

          <p className="mt-2 text-2xl font-bold text-red-400">
            {summary.errors}
          </p>
        </div>
      </div>

      {/* Validation Results */}

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
        <div className="border-b border-slate-800 px-6 py-4">
          <h3 className="text-lg font-semibold text-white">
            Validation Results
          </h3>
        </div>

        <div className="divide-y divide-slate-800">
          {results.map((file) => (
            <div
              key={file.id}
              className="p-5"
            >
              <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
                <div>
                  <div className="flex items-center gap-2">
                    {file.valid ? (
                      <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="h-5 w-5 text-red-400" />
                    )}

                    <h4 className="font-medium text-white">
                      {file.fileName}
                    </h4>
                  </div>

                  <p className="mt-1 text-sm text-slate-400">
                    {formatFileSize(
                      file.fileSize
                    )}
                  </p>
                </div>

                <span
                  className={`rounded-full px-3 py-1 text-xs font-medium ${
                    file.valid
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {file.valid
                    ? "Validated"
                    : "Rejected"}
                </span>
              </div>

              {file.issues.length >
                0 && (
                <div className="mt-4 flex flex-col gap-2">
                  {file.issues.map(
                    (
                      issue,
                      index
                    ) => (
                      <div
                        key={index}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${getSeverityColor(
                          issue.severity
                        )}`}
                      >
                        {getIssueIcon(
                          issue.type
                        )}

                        <span>
                          {
                            issue.message
                          }
                        </span>
                      </div>
                    )
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default FileValidation;