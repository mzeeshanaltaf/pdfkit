"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatBytes, formatPageCount } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Thumbnail } from "./thumbnail";
import type { ToolFile } from "./types";

interface FileCardProps {
  file: ToolFile;
  index: number;
  onRemove: (id: string) => void;
  /** Per-tool controls shown over the card on hover, e.g. the Rotate tool's turn buttons. */
  actions?: ReactNode;
}

export function FileCard({ file, index, onRemove, actions }: FileCardProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: file.id });

  const meta = [formatBytes(file.size), formatPageCount(file.pageCount)]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "group relative flex flex-col rounded-xl border border-border bg-card p-3 shadow-xs transition-shadow",
        file.error && "border-destructive/50",
        isDragging && "z-10 opacity-80 shadow-lg",
      )}
    >
      <Thumbnail
        src={file.thumbnail}
        alt={`First page of ${file.name}`}
        rotation={file.rotation}
        failed={Boolean(file.error)}
      />

      <div className="mt-3 min-w-0">
        <p className="truncate text-sm font-medium" title={file.name}>
          {file.name}
        </p>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {file.error ? file.error.message : meta}
        </p>
      </div>

      <div className="absolute inset-x-2 top-2 flex items-start justify-between opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <Button
          ref={setActivatorNodeRef}
          variant="secondary"
          size="icon-xs"
          className="cursor-grab active:cursor-grabbing"
          aria-label={`Reorder ${file.name}, currently position ${index + 1}`}
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden />
        </Button>

        <div className="flex items-center gap-1">
          {actions}
          <Button
            variant="secondary"
            size="icon-xs"
            aria-label={`Remove ${file.name}`}
            onClick={() => onRemove(file.id)}
          >
            <X aria-hidden />
          </Button>
        </div>
      </div>
    </li>
  );
}
