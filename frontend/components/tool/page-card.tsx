"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { RotateCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useInView } from "@/hooks/use-in-view";
import { renderThumbnail } from "@/lib/pdf/thumbnails";
import { cn } from "@/lib/utils";

import { Thumbnail } from "./thumbnail";
import type { ToolPage } from "./types";

interface PageCardProps {
  page: ToolPage;
  file: File;
  /** 1-based position in the grid, which is what the label under the card shows. */
  position: number;
  onRotate?: (id: string) => void;
  onDelete?: (id: string) => void;
  /** Colour chip letter when pages come from more than one file (A, B, C ...). */
  sourceLabel?: string;
}

export function PageCard({
  page,
  file,
  position,
  onRotate,
  onDelete,
  sourceLabel,
}: PageCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: page.id,
  });

  const containerRef = useRef<HTMLLIElement>(null);
  const inView = useInView(containerRef);
  const [thumbnail, setThumbnail] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // Documents can run to hundreds of pages, so a render is only started once the card is
  // near the viewport. Rotation is applied as a transform, so it never triggers a re-render.
  useEffect(() => {
    if (!inView) return;
    let active = true;
    renderThumbnail(page.fileId, file, page.pageNumber, { maxSize: 200 })
      .then((src) => {
        if (active) setThumbnail(src);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [inView, file, page.fileId, page.pageNumber]);

  return (
    <li
      ref={(node) => {
        containerRef.current = node;
        setNodeRef(node);
      }}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "group relative flex cursor-grab flex-col rounded-xl border border-border bg-card p-2 active:cursor-grabbing",
        isDragging && "z-10 opacity-80 shadow-lg",
      )}
      {...attributes}
      {...listeners}
    >
      <Thumbnail
        src={thumbnail}
        alt={`Page ${page.pageNumber}`}
        rotation={page.rotation}
        failed={failed}
      />

      {/* The number is the page's position in the output; the letter says which file it came from. */}
      {sourceLabel && (
        <span
          className="absolute top-3.5 left-3.5 rounded-md border border-border bg-background/90 px-1.5 text-[10px] font-medium text-muted-foreground"
          title={`From file ${sourceLabel}`}
        >
          {sourceLabel}
        </span>
      )}

      <p className="mt-2 text-center text-xs text-muted-foreground">{position}</p>

      {(onRotate || onDelete) && (
        <div className="absolute inset-x-1.5 top-1.5 flex justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {onRotate && (
            <Button
              variant="secondary"
              size="icon-xs"
              aria-label={`Rotate page ${position}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => onRotate(page.id)}
            >
              <RotateCw aria-hidden />
            </Button>
          )}
          {onDelete && (
            <Button
              variant="secondary"
              size="icon-xs"
              aria-label={`Delete page ${position}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => onDelete(page.id)}
            >
              <Trash2 aria-hidden />
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
