"use client";

import { useCallback, useState } from "react";

import type { ToolFile, ToolPage } from "./types";

export interface ToolPagesApi {
  pages: ToolPage[];
  reorderPages: (activeId: string, overId: string) => void;
  rotatePage: (id: string) => void;
  deletePage: (id: string) => void;
  /** Back to every page of every loaded file, in file order. */
  resetPages: () => void;
}

function pageId(fileId: string, pageNumber: number): string {
  return `${fileId}#${pageNumber}`;
}

/** Every page of every readable file, in the order the files are listed. */
function buildPages(files: ToolFile[]): ToolPage[] {
  const pages: ToolPage[] = [];
  for (const file of files) {
    if (file.error || file.pageCount === null) continue;
    for (let pageNumber = 1; pageNumber <= file.pageCount; pageNumber += 1) {
      pages.push({ id: pageId(file.id, pageNumber), fileId: file.id, pageNumber, rotation: 0 });
    }
  }
  return pages;
}

/**
 * Merges the user's edits with the current file list: pages the user reordered, rotated or
 * deleted keep their state, pages from a newly added file are appended, and pages from a
 * removed file disappear.
 */
function sync(current: ToolPage[], files: ToolFile[], deleted: Set<string>): ToolPage[] {
  const desired = buildPages(files);
  const desiredIds = new Set(desired.map((page) => page.id));
  const byId = new Map(current.map((page) => [page.id, page]));

  const kept = current.filter((page) => desiredIds.has(page.id));
  const appended = desired.filter((page) => !byId.has(page.id) && !deleted.has(page.id));

  return [...kept, ...appended];
}

/**
 * Page-level state for the tools whose canvas is a PageGrid rather than a FileGrid.
 *
 * The page list is derived from the file list but is not a pure function of it, because the
 * user reorders and deletes pages. It is therefore adjusted during render when the files
 * change, which is React's documented way to keep derived state in step without an effect.
 */
export function useToolPages(files: ToolFile[]): ToolPagesApi {
  const signature = files.map((file) => `${file.id}:${file.pageCount ?? "?"}:${file.error ? "x" : ""}`).join(",");

  const [pages, setPages] = useState<ToolPage[]>(() => buildPages(files));
  const [deleted, setDeleted] = useState<Set<string>>(() => new Set());
  const [lastSignature, setLastSignature] = useState(signature);

  if (signature !== lastSignature) {
    setLastSignature(signature);
    setPages(sync(pages, files, deleted));
  }

  const reorderPages = useCallback((activeId: string, overId: string) => {
    if (activeId === overId) return;
    setPages((current) => {
      const from = current.findIndex((page) => page.id === activeId);
      const to = current.findIndex((page) => page.id === overId);
      if (from === -1 || to === -1) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }, []);

  const rotatePage = useCallback((id: string) => {
    setPages((current) =>
      current.map((page) =>
        page.id === id ? { ...page, rotation: (page.rotation + 90) % 360 } : page,
      ),
    );
  }, []);

  const deletePage = useCallback((id: string) => {
    // Remembered so that re-syncing after a file is added does not resurrect it.
    setDeleted((current) => new Set(current).add(id));
    setPages((current) => current.filter((page) => page.id !== id));
  }, []);

  const resetPages = useCallback(() => {
    setDeleted(new Set());
    setPages(buildPages(files));
  }, [files]);

  return { pages, reorderPages, rotatePage, deletePage, resetPages };
}
