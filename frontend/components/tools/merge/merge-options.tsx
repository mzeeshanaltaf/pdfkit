"use client";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { formatPageCount } from "@/lib/format";

/**
 * Merge has no settings, only an order, so the panel's job is to make that order legible:
 * the same sequence the grid shows, as a numbered list that is readable at a glance and to
 * a screen reader, plus what the output will be.
 */
export function MergeOptions() {
  const { files } = useToolShell();
  const readable = files.filter((file) => !file.error);
  const totalPages = readable.reduce((sum, file) => sum + (file.pageCount ?? 0), 0);
  const ready = readable.every((file) => file.pageCount !== null);

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-sm font-medium">Merge order</h2>
        <ol className="mt-3 space-y-1.5">
          {files.map((file, index) => (
            <li key={file.id} className="flex items-center gap-2.5 text-sm">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-medium tabular-nums text-muted-foreground">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate" title={file.name}>
                {file.name}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {file.error ? "unreadable" : formatPageCount(file.pageCount)}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {readable.length < 2 ? (
        <p className="rounded-lg border border-dashed border-border p-3 text-sm leading-relaxed text-muted-foreground">
          Add at least one more PDF to merge. Use the <span aria-hidden>+</span>
          <span className="sr-only">add files</span> button above the grid.
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          One PDF of{" "}
          <span className="font-medium text-foreground">
            {ready ? formatPageCount(totalPages) : "…"}
          </span>{" "}
          from {readable.length} files.
        </p>
      )}
    </div>
  );
}
