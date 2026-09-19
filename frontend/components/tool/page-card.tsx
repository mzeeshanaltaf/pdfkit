"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { FilePlus2, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useInView } from "@/hooks/use-in-view";
import { renderThumbnail } from "@/lib/pdf/thumbnails";
import { cn } from "@/lib/utils";

import { SourceChip } from "./source-chip";
import { Thumbnail } from "./thumbnail";
import type { ToolPage } from "./types";

interface PageCardProps {
  page: ToolPage;
  /** The source document, or null when this card is an inserted blank page. */
  file: File | null;
  /** 1-based position in the grid, which is what the label under the card shows. */
  position: number;
  onRotate?: (id: string) => void;
  onDelete?: (id: string) => void;
  /** Adds a blank page directly after this one. */
  onInsertAfter?: (id: string) => void;
  /** Position of the source file in the workspace list; drives the letter and colour chip. */
  sourceIndex?: number;
}

export function PageCard({
  page,
  file,
  position,
  onRotate,
  onDelete,
  onInsertAfter,
  sourceIndex,
}: PageCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: page.id,
  });

  const containerRef = useRef<HTMLLIElement>(null);
  const inView = useInView(containerRef);
  const [thumbnail, setThumbnail] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const blank = page.fileId === null;

  // Documents can run to hundreds of pages, so a render is only started once the card is
  // near the viewport. Rotation is applied as a transform, so it never triggers a re-render.
  useEffect(() => {
    if (!inView || !file || page.fileId === null) return;
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
      {blank ? (
        // Deliberately white in both themes: the page this stands for is white paper, and a
        // dark card next to the real thumbnails reads as a failed render rather than a blank.
        <div className="flex aspect-3/4 w-full items-center justify-center rounded-md border border-dashed border-zinc-300 bg-white text-[11px] text-zinc-500">
          Blank
        </div>
      ) : (
        <Thumbnail
          src={thumbnail}
          alt={`Page ${page.pageNumber}`}
          rotation={page.rotation}
          failed={failed}
        />
      )}

      {/* The number is the page's position in the output; the chip says which file it came from. */}
      {sourceIndex !== undefined && !blank && (
        <SourceChip index={sourceIndex} className="absolute top-3.5 left-3.5 bg-background/95" />
      )}

      <p className="mt-2 text-center text-xs text-muted-foreground">{position}</p>

      {(onRotate || onDelete || onInsertAfter) && (
        <div className="absolute inset-x-1.5 top-1.5 flex justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {onInsertAfter && (
            <Button
              variant="secondary"
              size="icon-xs"
              aria-label={`Insert a blank page after position ${position}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => onInsertAfter(page.id)}
            >
              <FilePlus2 aria-hidden />
            </Button>
          )}
          {onRotate && !blank && (
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
