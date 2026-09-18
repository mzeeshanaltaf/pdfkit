"use client";

import type { ReactNode } from "react";

import { SortableGrid } from "./sortable-grid";
import { FileCard } from "./file-card";
import type { ToolFile } from "./types";

interface FileGridProps {
  files: ToolFile[];
  onRemove: (id: string) => void;
  onReorder: (activeId: string, overId: string) => void;
  /** Rendered into each card's hover overlay, e.g. per-file rotate buttons. */
  renderActions?: (file: ToolFile) => ReactNode;
}

export function FileGrid({ files, onRemove, onReorder, renderActions }: FileGridProps) {
  return (
    <SortableGrid
      ids={files.map((file) => file.id)}
      onReorder={onReorder}
      label="Selected files"
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
    >
      {files.map((file, index) => (
        <FileCard
          key={file.id}
          file={file}
          index={index}
          onRemove={onRemove}
          actions={renderActions?.(file)}
        />
      ))}
    </SortableGrid>
  );
}
