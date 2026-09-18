"use client";

import { SortableGrid } from "./sortable-grid";
import { PageCard } from "./page-card";
import type { ToolFile, ToolPage } from "./types";

interface PageGridProps {
  pages: ToolPage[];
  files: ToolFile[];
  onReorder: (activeId: string, overId: string) => void;
  onRotate?: (id: string) => void;
  onDelete?: (id: string) => void;
}

/** Page-level canvas used by Organize, Split and Page numbers. */
export function PageGrid({ pages, files, onReorder, onRotate, onDelete }: PageGridProps) {
  const filesById = new Map(files.map((file) => [file.id, file]));
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
        const source = filesById.get(page.fileId);
        if (!source) return null;
        return (
          <PageCard
            key={page.id}
            page={page}
            file={source.file}
            position={index + 1}
            onRotate={onRotate}
            onDelete={onDelete}
            sourceLabel={
              showSource
                ? String.fromCharCode(65 + files.findIndex((file) => file.id === page.fileId))
                : undefined
            }
          />
        );
      })}
    </SortableGrid>
  );
}
