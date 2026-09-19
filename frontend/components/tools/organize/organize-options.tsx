"use client";

import { ArrowDownAZ, ArrowDownZA, FilePlus2, Undo2, X } from "lucide-react";

import { SourceChip } from "@/components/tool/source-chip";
import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";
import { formatPageCount } from "@/lib/format";

import {
  insertBlankAfter,
  pageCountsByFile,
  resetOrganize,
  sortPages,
  syncOrganize,
  type OrganizeState,
} from "./organize-state";

interface OrganizeOptionsProps {
  state: OrganizeState;
  onChange: (next: OrganizeState) => void;
}

/**
 * Organize has no settings, only a grid, so the panel's job is to make the grid legible:
 * which file each colour is, how much of each one survived the edit, and the operations that
 * are awkward to do card by card.
 */
export function OrganizeOptions({ state, onChange }: OrganizeOptionsProps) {
  const { files, removeFile } = useToolShell();
  const synced = syncOrganize(state, files);
  const counts = pageCountsByFile(synced.pages);
  const blanks = synced.pages.filter((page) => page.fileId === null).length;
  const rotated = synced.pages.filter((page) => page.rotation !== 0).length;

  return (
    <div className="space-y-5">
      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium">Files</h2>
          <Button
            variant="ghost"
            size="sm"
            className="-mr-2 h-7"
            onClick={() => onChange(resetOrganize(files))}
          >
            <Undo2 aria-hidden />
            Reset all
          </Button>
        </div>

        <ul className="mt-2 space-y-1.5">
          {files.map((file, index) => (
            <li key={file.id} className="flex items-center gap-2.5 text-sm">
              <SourceChip index={index} title={file.name} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate" title={file.name}>
                {file.name}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {file.error
                  ? "unreadable"
                  : `${counts.get(file.id) ?? 0}/${file.pageCount ?? "…"}`}
              </span>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${file.name}`}
                onClick={() => removeFile(file.id)}
              >
                <X aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3 border-t border-border pt-5">
        <h2 className="text-sm font-medium">Arrange</h2>
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={() => onChange(sortPages(synced, files, "asc"))}>
            <ArrowDownAZ aria-hidden />
            Sort 1-9
          </Button>
          <Button variant="outline" onClick={() => onChange(sortPages(synced, files, "desc"))}>
            <ArrowDownZA aria-hidden />
            Sort 9-1
          </Button>
        </div>
        <Button
          variant="outline"
          className="w-full"
          onClick={() => onChange(insertBlankAfter(synced, null))}
        >
          <FilePlus2 aria-hidden />
          Add a blank page
        </Button>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Drag a page to move it. Hover one to rotate it, delete it, or slip a blank page in
          behind it.
        </p>
      </section>

      <p className="border-t border-border pt-5 text-sm text-muted-foreground">
        One PDF of{" "}
        <span className="font-medium text-foreground">
          {formatPageCount(synced.pages.length)}
        </span>
        {blanks > 0 && `, ${blanks} of them blank`}
        {rotated > 0 && `, ${rotated} rotated`}.
      </p>
    </div>
  );
}
