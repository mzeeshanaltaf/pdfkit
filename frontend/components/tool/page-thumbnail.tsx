"use client";

import { useEffect, useRef, useState } from "react";

import { useInView } from "@/hooks/use-in-view";
import { renderThumbnail } from "@/lib/pdf/thumbnails";

import { Thumbnail } from "./thumbnail";

interface PageThumbnailProps {
  /** Stable key for the source file, normally the ToolFile id, used for cache scoping. */
  fileKey: string;
  file: File;
  pageNumber: number;
  maxSize?: number;
  className?: string;
}

/**
 * A read-only preview of one page. Unlike `PageCard` it is not draggable and carries no
 * controls, which is what the Split preview wants: a picture of what comes out, not an
 * editable grid.
 */
export function PageThumbnail({
  fileKey,
  file,
  pageNumber,
  maxSize = 160,
  className,
}: PageThumbnailProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const inView = useInView(containerRef);
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  // Splitting every page of a long document lays out a lot of previews; only the ones near
  // the viewport are worth a canvas render.
  useEffect(() => {
    if (!inView) return;
    let active = true;

    renderThumbnail(fileKey, file, pageNumber, { maxSize })
      .then((rendered) => {
        if (active) setSource(rendered);
      })
      .catch(() => {
        if (active) setFailed(true);
      });

    return () => {
      active = false;
    };
  }, [inView, fileKey, file, pageNumber, maxSize]);

  return (
    <div ref={containerRef} className={className}>
      <Thumbnail src={source} alt={`Page ${pageNumber}`} failed={failed} />
    </div>
  );
}
