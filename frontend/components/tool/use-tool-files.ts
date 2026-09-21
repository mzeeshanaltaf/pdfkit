"use client";

import { useCallback, useRef, useState } from "react";

import {
  BROWSER_SOFT_BATCH_BYTES,
  BROWSER_SOFT_BATCH_LABEL,
  MAX_BATCH_BYTES,
  MAX_BATCH_LABEL,
  MAX_FILES_PER_BATCH,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_LABEL,
} from "@/lib/constants";
import { inspectPdf, PdfLoadError, pdfErrorMessage, releasePdfJsDocument } from "@/lib/pdf/load";
import { clearThumbnailCache, renderThumbnail } from "@/lib/pdf/thumbnails";
import type { Tool } from "@/lib/tools";

import type { ToolFile } from "./types";

export type SortDirection = "asc" | "desc";

export interface AddFilesResult {
  added: number;
  /** One message per rejected file, ready to show in a toast. */
  rejected: string[];
  /** A one-time, non-blocking nudge — e.g. a browser batch getting large. */
  warning?: string;
}

function isPdf(file: File): boolean {
  return file.name.toLowerCase().endsWith(".pdf") || file.type === "application/pdf";
}

export interface ToolFilesApi {
  files: ToolFile[];
  addFiles: (incoming: File[]) => AddFilesResult;
  removeFile: (id: string) => void;
  reorderFiles: (activeId: string, overId: string) => void;
  sortFiles: (direction: SortDirection) => void;
  rotateFile: (id: string, delta: number) => void;
  rotateAll: (delta: number) => void;
  resetRotations: () => void;
  clearFiles: () => void;
}

/**
 * Owns the workspace file list: validation on the way in, background page-count and
 * thumbnail loading, and the reorder / rotate / remove operations the grids drive.
 */
export function useToolFiles(tool: Tool): ToolFilesApi {
  const [files, setFiles] = useState<ToolFile[]>([]);
  // Fires once per workspace so the browser-batch nudge does not repeat on every drop.
  const warnedRef = useRef(false);

  const patch = useCallback((id: string, changes: Partial<ToolFile>) => {
    setFiles((current) =>
      current.map((entry) => (entry.id === id ? { ...entry, ...changes } : entry)),
    );
  }, []);

  const hydrate = useCallback(
    async (entry: ToolFile) => {
      try {
        const { pageCount } = await inspectPdf(entry.file);
        patch(entry.id, { pageCount });
        const thumbnail = await renderThumbnail(entry.id, entry.file, 1);
        patch(entry.id, { thumbnail });
      } catch (error) {
        const kind = error instanceof PdfLoadError ? error.kind : "invalid";
        patch(entry.id, { error: { kind, message: pdfErrorMessage(kind) } });
      }
    },
    [patch],
  );

  const addFiles = useCallback(
    (incoming: File[]): AddFilesResult => {
      const rejected: string[] = [];
      const accepted: ToolFile[] = [];
      // Backend/hybrid tools are the only ones bound by the batch caps; browser tools
      // never post, so there is no server cost or timeout to protect.
      const capped = tool.runsIn !== "browser";

      let count = tool.multiple ? files.length : 0;
      let totalBytes = tool.multiple ? files.reduce((sum, entry) => sum + entry.size, 0) : 0;

      for (const file of incoming) {
        if (!isPdf(file)) {
          rejected.push(`${file.name} is not a PDF.`);
          continue;
        }
        if (capped && file.size > MAX_UPLOAD_BYTES) {
          rejected.push(`${file.name} is over the ${MAX_UPLOAD_LABEL} limit.`);
          continue;
        }
        if (!tool.multiple && accepted.length === 1) {
          rejected.push(`${tool.name} takes one file at a time.`);
          continue;
        }
        if (capped && count + 1 > MAX_FILES_PER_BATCH) {
          rejected.push(`${file.name} was skipped — a batch is limited to ${MAX_FILES_PER_BATCH} files.`);
          continue;
        }
        if (capped && totalBytes + file.size > MAX_BATCH_BYTES) {
          rejected.push(
            `${file.name} was skipped — this batch is over the ${MAX_BATCH_LABEL} combined limit.`,
          );
          continue;
        }

        count += 1;
        totalBytes += file.size;
        accepted.push({
          id: crypto.randomUUID(),
          file,
          name: file.name,
          size: file.size,
          pageCount: null,
          thumbnail: null,
          rotation: 0,
          error: null,
        });
      }

      let warning: string | undefined;
      if (!capped && !warnedRef.current && totalBytes > BROWSER_SOFT_BATCH_BYTES) {
        warnedRef.current = true;
        warning = `That's over ${BROWSER_SOFT_BATCH_LABEL} in one batch — very large batches can slow down or crash your browser tab, depending on your device.`;
      }

      if (accepted.length > 0) {
        setFiles((current) => {
          // Single-file tools replace what is loaded rather than growing the list.
          if (tool.multiple) return [...current, ...accepted];
          for (const entry of current) {
            clearThumbnailCache(entry.id);
            void releasePdfJsDocument(entry.file);
          }
          return accepted;
        });
        for (const entry of accepted) void hydrate(entry);
      }

      return { added: accepted.length, rejected, warning };
    },
    [files, hydrate, tool],
  );

  const removeFile = useCallback((id: string) => {
    setFiles((current) => {
      const entry = current.find((candidate) => candidate.id === id);
      if (entry) {
        clearThumbnailCache(entry.id);
        void releasePdfJsDocument(entry.file);
      }
      return current.filter((candidate) => candidate.id !== id);
    });
  }, []);

  const reorderFiles = useCallback((activeId: string, overId: string) => {
    if (activeId === overId) return;
    setFiles((current) => {
      const from = current.findIndex((entry) => entry.id === activeId);
      const to = current.findIndex((entry) => entry.id === overId);
      if (from === -1 || to === -1) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }, []);

  const sortFiles = useCallback((direction: SortDirection) => {
    setFiles((current) =>
      [...current].sort((a, b) => {
        const compared = a.name.localeCompare(b.name, undefined, { numeric: true });
        return direction === "asc" ? compared : -compared;
      }),
    );
  }, []);

  const rotateFile = useCallback((id: string, delta: number) => {
    setFiles((current) =>
      current.map((entry) =>
        entry.id === id ? { ...entry, rotation: (entry.rotation + delta + 360) % 360 } : entry,
      ),
    );
  }, []);

  const rotateAll = useCallback((delta: number) => {
    setFiles((current) =>
      current.map((entry) => ({ ...entry, rotation: (entry.rotation + delta + 360) % 360 })),
    );
  }, []);

  const resetRotations = useCallback(() => {
    setFiles((current) => current.map((entry) => ({ ...entry, rotation: 0 })));
  }, []);

  const clearFiles = useCallback(() => {
    warnedRef.current = false;
    setFiles((current) => {
      for (const entry of current) {
        clearThumbnailCache(entry.id);
        void releasePdfJsDocument(entry.file);
      }
      return [];
    });
  }, []);

  return {
    files,
    addFiles,
    removeFile,
    reorderFiles,
    sortFiles,
    rotateFile,
    rotateAll,
    resetRotations,
    clearFiles,
  };
}
