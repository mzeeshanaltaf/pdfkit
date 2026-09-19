import type { PdfErrorKind } from "@/lib/pdf/load";

export interface ToolFileError {
  kind: PdfErrorKind;
  message: string;
}

/**
 * One entry in the workspace file list. `pageCount` and `thumbnail` stay null until the
 * background load finishes, which is how the cards know to show a skeleton.
 */
export interface ToolFile {
  id: string;
  file: File;
  name: string;
  size: number;
  pageCount: number | null;
  thumbnail: string | null;
  /** Extra rotation in degrees the user has applied to the whole file, 0/90/180/270. */
  rotation: number;
  error: ToolFileError | null;
}

/** A single page in a page-level grid (Organize, Split preview, Page numbers preview). */
export interface ToolPage {
  id: string;
  /** null for a blank page the user inserted, which has no source document behind it. */
  fileId: string | null;
  /** 1-based page number inside its source file; 0 for a blank page. */
  pageNumber: number;
  rotation: number;
}

export type ToolStatus = "select" | "configure" | "processing" | "done" | "error";

/** What ToolShell actually stores. "select" vs "configure" is derived from the file list. */
export type ToolPhase = "idle" | "processing" | "done" | "error";

export interface ToolResult {
  blob: Blob;
  filename: string;
  /** Optional size comparison, used by Compress. */
  originalSize?: number;
  resultSize?: number;
  /** Replaces the default "Download" label, e.g. "Download 12 JPG images". */
  downloadLabel?: string;
}

export interface ToolRunContext {
  files: ToolFile[];
  /** 0-100 while uploading, or null for an indeterminate "Processing" state. */
  setProgress: (progress: number | null) => void;
  setStage: (stage: string) => void;
  signal: AbortSignal;
}

export type ToolProcess = (context: ToolRunContext) => Promise<ToolResult>;
