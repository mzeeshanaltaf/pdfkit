"use client";

import { RotateCcw, RotateCw, Undo2 } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";

/**
 * Turning everything at once is the common case, so the two big buttons drive the whole
 * set; per-file adjustments are made on the cards themselves. What each file ends up at is
 * listed underneath, because the thumbnails alone do not say "90°" out loud.
 */
export function RotateOptions() {
  const { files, rotateAll, resetRotations } = useToolShell();
  const readable = files.filter((file) => !file.error);
  const rotated = readable.filter((file) => file.rotation !== 0);
  const multiple = readable.length > 1;

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-sm font-medium">
          {multiple ? "Turn every file" : "Turn every page"}
        </h2>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Button
            variant="outline"
            className="h-20 flex-col gap-1.5 text-xs font-medium"
            onClick={() => rotateAll(-90)}
          >
            <RotateCcw className="size-6" aria-hidden />
            Left
          </Button>
          <Button
            variant="outline"
            className="h-20 flex-col gap-1.5 text-xs font-medium"
            onClick={() => rotateAll(90)}
          >
            <RotateCw className="size-6" aria-hidden />
            Right
          </Button>
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium">Rotation</h2>
          <Button
            variant="ghost"
            size="sm"
            className="-mr-2 h-7"
            disabled={rotated.length === 0}
            onClick={resetRotations}
          >
            <Undo2 aria-hidden />
            Reset all
          </Button>
        </div>

        <ul className="mt-2 space-y-1.5">
          {readable.map((file) => (
            <li key={file.id} className="flex items-center gap-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate" title={file.name}>
                {file.name}
              </span>
              <span
                className={
                  file.rotation === 0
                    ? "shrink-0 text-xs text-muted-foreground"
                    : "shrink-0 text-xs font-medium tabular-nums text-brand"
                }
              >
                {file.rotation}&deg;
              </span>
            </li>
          ))}
        </ul>
      </section>

      {rotated.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-3 text-sm leading-relaxed text-muted-foreground">
          Pick a direction to turn the pages. Hover a card to turn just that file.
        </p>
      ) : (
        multiple && (
          <p className="text-sm text-muted-foreground">
            {readable.length} files come back as a ZIP.
          </p>
        )
      )}
    </div>
  );
}
