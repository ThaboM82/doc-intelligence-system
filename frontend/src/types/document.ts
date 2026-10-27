export interface Document {
  id: string;

  fileName: string;

  fileType: string;

  size: number;

  status:
    | "Processing"
    | "Completed"
    | "Failed";

  uploadedAt: string;

  confidence?: number;
}