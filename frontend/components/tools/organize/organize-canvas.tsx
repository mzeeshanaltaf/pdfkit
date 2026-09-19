"use client";

import { LayoutGrid } from "lucide-react";

import { PageGrid } from "@/components/tool/page-grid";
import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";

import {
  deletePage,
  insertBlankAfter,
  movePage,
  resetOrganize,
  rotatePage,
  syncOrganize,
  type OrganizeState,
} from "./organize-state";

interface OrganizeCanvasProps {
  state: OrganizeState;
  onChange: (next: OrganizeState) => void;
}

/**
 * The combined page grid: every page of every loaded file in one list, in the order the new
 * document will have. Pages are tagged with their source file's letter and colour, so a page
 * dragged between two documents can still be told apart from its new neighbours.
 */
export function OrganizeCanvas({ state, onChange }: OrganizeCanvasProps) {
  const { files } = useToolShell();
  const synced = syncOrganize(state, files);
  const loading = files.some((file) => !file.error && file.pageCount === null);

  if (synced.pages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-center">
        <LayoutGrid className="size-6 text-muted-foreground" aria-hidden />
        <p className="max-w-xs text-sm text-muted-foreground">
          {loading ? "Reading the pages…" : "Every page has been deleted."}
        </p>
        {!loading && (
          <Button variant="outline" size="sm" onClick={() => onChange(resetOrganize(files))}>
            Bring them back
          </Button>
        )}
      </div>
    );
  }

  return (
    <PageGrid
      pages={synced.pages}
      files={files}
      onReorder={(activeId, overId) => onChange(movePage(synced, activeId, overId))}
      onRotate={(id) => onChange(rotatePage(synced, id))}
      onDelete={(id) => onChange(deletePage(synced, id))}
      onInsertAfter={(id) => onChange(insertBlankAfter(synced, id))}
    />
  );
}
