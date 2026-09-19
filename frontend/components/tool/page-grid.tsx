"use client";

import { PageCard } from "./page-card";
import { SortableGrid } from "./sortable-grid";
import type { ToolFile, ToolPage } from "./types";

interface PageGridProps {
  pages: ToolPage[];
  files: ToolFile[];
  onReorder: (activeId: string, overId: string) => void;
  onRotate?: (id: string) => void;
  onDelete?: (id: string) => void;
  onInsertAfter?: (id: string) => void;
}

/** Page-level canvas: every page of every loaded file in one combined, reorderable grid. */
export function PageGrid({
  pages,
  files,
  onReorder,
  onRotate,
  onDelete,
  onInsertAfter,
}: PageGridProps) {
  const indexById = new Map(files.map((file, index) => [file.id, index]));
  // Only worth labelling the source when pages come from more than one document.
  const showSource = files.length > 1;

  return (
    <SortableGrid
      ids={pages.map((page) => page.id)}
      onReorder={onReorder}
      label="Pages"
      className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8"
    >
      {pages.map((page, index) => {
        const sourceIndex = page.fileId === null ? undefined : indexById.get(page.fileId);
        // A page whose file has been removed is on its way out; skip it for this render.
        if (page.fileId !== null && sourceIndex === undefined) return null;

        return (
          <PageCard
            key={page.id}
            page={page}
            file={sourceIndex === undefined ? null : files[sourceIndex].file}
            position={index + 1}
            onRotate={onRotate}
            onDelete={onDelete}
            onInsertAfter={onInsertAfter}
            sourceIndex={showSource ? sourceIndex : undefined}
          />
        );
      })}
    </SortableGrid>
  );
}
