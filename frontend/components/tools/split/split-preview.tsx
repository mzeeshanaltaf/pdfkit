"use client";

import { Scissors } from "lucide-react";

import { PageThumbnail } from "@/components/tool/page-thumbnail";
import { useToolShell } from "@/components/tool/tool-shell-context";
import { formatPageCount } from "@/lib/format";
import type { SplitChunk } from "@/lib/pdf/split";

import { planFromState, type SplitState } from "./split-state";

/** Splitting page by page can plan hundreds of documents; past this it is wallpaper. */
const MAX_PREVIEWED = 24;

/**
 * Shows what the current options would produce: one card per output document, with its
 * first and last page. It is the whole reason Split does not use the generic page grid —
 * the interesting thing here is the grouping, not the individual pages.
 */
export function SplitPreview({ state }: { state: SplitState }) {
  const { files } = useToolShell();
  const file = files.find((entry) => !entry.error);
  const { chunks, issue } = planFromState(state, file?.pageCount ?? null);

  if (!file) return null;

  if (issue || !chunks) {
    return (
      <Placeholder>
        {issue ?? "Reading the document…"}
      </Placeholder>
    );
  }

  const shown = chunks.slice(0, MAX_PREVIEWED);
  const hidden = chunks.length - shown.length;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {chunks.length === 1
          ? `One PDF of ${formatPageCount(chunks[0].pages.length)}`
          : `${chunks.length} PDFs from ${file.name}`}
      </p>

      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {shown.map((chunk, index) => (
          <li
            key={`${chunk.label}-${index}`}
            className="rounded-xl border border-border bg-card p-3 shadow-xs"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-medium">
                {chunkTitle(chunk, index, state.mergeOutput)}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatPageCount(chunk.pages.length)}
              </span>
            </div>

            <div className="mt-3 flex items-center justify-center gap-2">
              <Edge fileId={file.id} file={file.file} page={chunk.pages[0]} />
              {chunk.pages.length > 1 && (
                <>
                  <span className="text-sm text-muted-foreground" aria-hidden>
                    &hellip;
                  </span>
                  <Edge
                    fileId={file.id}
                    file={file.file}
                    page={chunk.pages[chunk.pages.length - 1]}
                  />
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      {hidden > 0 && (
        <p className="text-sm text-muted-foreground">
          &hellip; and {hidden} more {hidden === 1 ? "PDF" : "PDFs"}, not previewed.
        </p>
      )}
    </div>
  );
}

/** The first or last page of one output document, captioned with its source page number. */
function Edge({ fileId, file, page }: { fileId: string; file: File; page: number }) {
  return (
    <div className="w-20">
      <PageThumbnail fileKey={fileId} file={file} pageNumber={page} />
      <p className="mt-1.5 text-center text-xs text-muted-foreground">Page {page}</p>
    </div>
  );
}

function chunkTitle(chunk: SplitChunk, index: number, merged: boolean): string {
  if (merged) return "Merged PDF";
  if (chunk.pages.length === 1) return `Page ${chunk.pages[0]}`;
  return `Range ${index + 1}`;
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-center">
      <Scissors className="size-6 text-muted-foreground" aria-hidden />
      <p className="max-w-xs text-sm text-muted-foreground">{children}</p>
    </div>
  );
}
