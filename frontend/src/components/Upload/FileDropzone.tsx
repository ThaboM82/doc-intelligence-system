import React, {
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  UploadCloud,
  FileText,
  AlertTriangle,
  CheckCircle2,
  X,
  Files,
} from "lucide-react";

export interface UploadedFile {
  file: File;
  id: string;
  status:
    | "pending"
    | "uploading"
    | "completed"
    | "failed";
  progress: number;
  error?: string;
}

interface FileDropzoneProps {
  onFilesSelected: (files: File[]) => void;
  acceptedTypes?: string[];
  maxFiles?: number;
  maxFileSizeMB?: number;
  disabled?: boolean;
}

const DEFAULT_ACCEPTED_TYPES = [
  ".pdf",
  ".docx",
  ".xlsx",
  ".pptx",
  ".txt",
  ".csv",
];

const FileDropzone: React.FC<
  FileDropzoneProps
> = ({
  onFilesSelected,
  acceptedTypes = DEFAULT_ACCEPTED_TYPES,
  maxFiles = 20,
  maxFileSizeMB = 100,
  disabled = false,
}) => {
  const inputRef =
    useRef<HTMLInputElement>(null);

  const [isDragging, setIsDragging] =
    useState(false);

  const [error, setError] =
    useState<string | null>(null);

  const [files, setFiles] = useState<
    UploadedFile[]
  >([]);

  const maxBytes = useMemo(
    () => maxFileSizeMB * 1024 * 1024,
    [maxFileSizeMB]
  );

  const validateFiles = useCallback(
    (incomingFiles: File[]) => {
      setError(null);

      if (
        files.length + incomingFiles.length >
        maxFiles
      ) {
        setError(
          `Maximum ${maxFiles} files allowed`
        );

        return [];
      }

      const validFiles = incomingFiles.filter(
        (file) => {
          const extension =
            "." +
            file.name
              .split(".")
              .pop()
              ?.toLowerCase();

          const extensionValid =
            acceptedTypes.includes(extension);

          const sizeValid =
            file.size <= maxBytes;

          if (!extensionValid) {
            setError(
              `Unsupported file type: ${file.name}`
            );
            return false;
          }

          if (!sizeValid) {
            setError(
              `${file.name} exceeds ${maxFileSizeMB}MB limit`
            );
            return false;
          }

          return true;
        }
      );

      return validFiles;
    },
    [
      files.length,
      maxFiles,
      acceptedTypes,
      maxBytes,
      maxFileSizeMB,
    ]
  );

  const processFiles = useCallback(
    (incomingFiles: File[]) => {
      const validFiles =
        validateFiles(incomingFiles);

      if (!validFiles.length) {
        return;
      }

      const uploads: UploadedFile[] =
        validFiles.map((file) => ({
          id: crypto.randomUUID(),
          file,
          status: "pending",
          progress: 0,
        }));

      setFiles((prev) => [
        ...prev,
        ...uploads,
      ]);

      onFilesSelected(validFiles);
    },
    [onFilesSelected, validateFiles]
  );

  const handleDrop = useCallback(
    (
      event: React.DragEvent<HTMLDivElement>
    ) => {
      event.preventDefault();
      setIsDragging(false);

      if (disabled) return;

      processFiles(
        Array.from(
          event.dataTransfer.files
        )
      );
    },
    [disabled, processFiles]
  );

  const handleBrowse = () => {
    if (!disabled) {
      inputRef.current?.click();
    }
  };

  const removeFile = (id: string) => {
    setFiles((prev) =>
      prev.filter(
        (uploadedFile) =>
          uploadedFile.id !== id
      )
    );
  };

  return (
    <div className="space-y-4">
      <div
        className={`rounded-2xl border-2 border-dashed transition-all duration-200 ${
          isDragging
            ? "border-indigo-500 bg-indigo-500/10"
            : "border-slate-700 bg-slate-900/50"
        } ${
          disabled
            ? "cursor-not-allowed opacity-50"
            : "cursor-pointer"
        }`}
        onClick={handleBrowse}
        onDragEnter={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() =>
          setIsDragging(false)
        }
        onDragOver={(e) =>
          e.preventDefault()
        }
        onDrop={handleDrop}
      >
        <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
          <div className="mb-4 rounded-full bg-indigo-500/10 p-4">
            <UploadCloud className="h-10 w-10 text-indigo-400" />
          </div>

          <h3 className="text-lg font-semibold text-white">
            Upload Documents
          </h3>

          <p className="mt-2 max-w-xl text-sm text-slate-400">
            Drag and drop files here or
            click to browse.
            Supported enterprise document
            formats include PDF, DOCX,
            XLSX, PPTX, TXT, and CSV.
          </p>

          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {acceptedTypes.map((type) => (
              <span
                key={type}
                className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300"
              >
                {type}
              </span>
            ))}
          </div>

          <p className="mt-4 text-xs text-slate-500">
            Maximum: {maxFiles} files |
            {maxFileSizeMB}MB each
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={acceptedTypes.join(",")}
          onChange={(e) =>
            processFiles(
              Array.from(
                e.target.files || []
              )
            )
          }
        />
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800 bg-red-900/20 p-3 text-red-300">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {files.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900">
          <div className="border-b border-slate-800 p-4">
            <div className="flex items-center gap-2">
              <Files className="h-5 w-5 text-indigo-400" />
              <span className="font-medium text-white">
                Selected Documents (
                {files.length})
              </span>
            </div>
          </div>

          <div className="divide-y divide-slate-800">
            {files.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between p-4"
              >
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-cyan-400" />

                  <div>
                    <div className="font-medium text-slate-200">
                      {item.file.name}
                    </div>

                    <div className="text-xs text-slate-500">
                      {(
                        item.file.size /
                        1024 /
                        1024
                      ).toFixed(2)}{" "}
                      MB
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <CheckCircle2 className="h-5 w-5 text-emerald-400" />

                  <button
                    type="button"
                    onClick={() =>
                      removeFile(item.id)
                    }
                    className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default FileDropzone;