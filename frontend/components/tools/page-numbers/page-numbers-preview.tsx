"use client";

import { Hash } from "lucide-react";

import { PageThumbnail } from "@/components/tool/page-thumbnail";
import { useToolShell } from "@/components/tool/tool-shell-context";
import type { HorizontalPosition, MarginSize, VerticalPosition } from "@/lib/pdf/pageNumbers";
import { cn } from "@/lib/utils";

import { planFromState, previewFile, type PageNumbersState } from "./page-numbers-state";

/** Past this the previews stop informing and start being wallpaper. */
const MAX_PREVIEWED = 24;

/** Inset of the dot from the edge of the sheet, as a share of the thumbnail. */
const MARGIN_INSET: Record<MarginSize, number> = {
  small: 0.05,
  recommended: 0.09,
  big: 0.15,
};

/**
 * Shows where the number will land: the real pages, with a red dot in the spot the options
 * point at. In facing mode the dot moves to the other edge on even pages, which is the
 * clearest way to show what that setting actually does.
 */
export function PageNumbersPreview({ state }: { state: PageNumbersState }) {
  const { files } = useToolShell();
  const file = previewFile(files, state.previewFileId);
  const { plan, issue } = planFromState(state, file?.pageCount ?? null);

  if (!file) return null;

  if (issue || !plan || file.pageCount === null) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-center">
        <Hash className="size-6 text-muted-foreground" aria-hidden />
        <p className="max-w-xs text-sm text-muted-foreground">
          {issue ?? "Reading the document…"}
        </p>
      </div>
    );
  }

  const numbered = new Map(plan.pages.map((page) => [page.pageNumber, page]));
  const shown = Math.min(file.pageCount, MAX_PREVIEWED);
  const hidden = file.pageCount - shown;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {plan.pages.length === 1
          ? "One page will be numbered"
          : `${plan.pages.length} of ${file.pageCount} pages will be numbered`}{" "}
        in {file.name}
      </p>

      <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
        {Array.from({ length: shown }, (_, index) => index + 1).map((pageNumber) => {
          const entry = numbered.get(pageNumber);

          return (
            <li key={pageNumber} className="rounded-xl border border-border bg-card p-2">
              <div className={cn("relative", !entry && "opacity-50")}>
                <PageThumbnail fileKey={file.id} file={file.file} pageNumber={pageNumber} />
                {entry && (
                  <span
                    className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-red-500 ring-2 ring-red-500/25"
                    style={dotStyle(state.position.vertical, entry.horizontal, state.margin)}
                    title={entry.text}
                  >
                    <span className="sr-only">{entry.text}</span>
                  </span>
                )}
              </div>
              <p className="mt-2 text-center text-xs text-muted-foreground">{pageNumber}</p>
            </li>
          );
        })}
      </ul>

      {hidden > 0 && (
        <p className="text-sm text-muted-foreground">
          &hellip; and {hidden} more {hidden === 1 ? "page" : "pages"}, not previewed.
        </p>
      )}
    </div>
  );
}

function dotStyle(
  vertical: VerticalPosition,
  horizontal: HorizontalPosition,
  margin: MarginSize,
): { left: string; top: string } {
  const inset = MARGIN_INSET[margin];
  const across = horizontal === "left" ? inset : horizontal === "right" ? 1 - inset : 0.5;
  const down = vertical === "top" ? inset : vertical === "bottom" ? 1 - inset : 0.5;
  return { left: `${across * 100}%`, top: `${down * 100}%` };
}
