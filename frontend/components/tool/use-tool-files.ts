"use client";

import { useCallback, useState } from "react";

import { MAX_UPLOAD_BYTES, MAX_UPLOAD_LABEL } from "@/lib/constants";
import { inspectPdf, PdfLoadError, pdfErrorMessage, releasePdfJsDocument } from "@/lib/pdf/load";
import { clearThumbnailCache, renderThumbnail } from "@/lib/pdf/thumbnails";
import type { Tool } from "@/lib/tools";

import type { ToolFile } from "./types";

export type SortDirection = "asc" | "desc";

export interface AddFilesResult {
  added: number;
  /** One message per rejected file, ready to show in a toast. */
  rejected: string[];
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
      // Backend tools are the only ones bound by the upload cap; browser tools never post.
      const capped = tool.runsIn !== "browser";

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

      return { added: accepted.length, rejected };
    },
    [hydrate, tool],
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
