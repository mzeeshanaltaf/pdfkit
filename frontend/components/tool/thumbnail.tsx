"use client";

import { FileWarning } from "lucide-react";

import { cn } from "@/lib/utils";

interface ThumbnailProps {
  src: string | null;
  alt: string;
  /** Degrees to spin the preview by. Applied with a transform, so it is free. */
  rotation?: number;
  failed?: boolean;
  className?: string;
}

/**
 * The paper preview shared by file cards and page cards, including its loading skeleton.
 * Rotation is visual only: the real page rotation is applied when the document is written.
 */
/**
 * Width divided by height of the frame below. A quarter turn swaps the image's axes, so it
 * has to shrink by this factor to keep fitting; without it the preview is clipped.
 */
const FRAME_ASPECT = 0.75;

export function Thumbnail({ src, alt, rotation = 0, failed = false, className }: ThumbnailProps) {
  const quarterTurn = rotation % 180 !== 0;
  const transform = rotation
    ? `rotate(${rotation}deg)${quarterTurn ? ` scale(${FRAME_ASPECT})` : ""}`
    : undefined;

  return (
    <div
      className={cn(
        "thumb-surface relative flex aspect-3/4 w-full items-center justify-center overflow-hidden rounded-md border border-border bg-background",
        className,
      )}
    >
      {failed ? (
        <FileWarning className="size-6 text-muted-foreground" aria-hidden />
      ) : src ? (
        // A data URL of a canvas render; next/image would add a network round trip for nothing.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt}
          className="max-h-full max-w-full object-contain transition-transform duration-200"
          style={transform ? { transform } : undefined}
          draggable={false}
        />
      ) : (
        <div className="size-full animate-pulse bg-muted" aria-hidden />
      )}
    </div>
  );
}
