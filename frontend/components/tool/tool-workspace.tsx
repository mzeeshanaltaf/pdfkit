"use client";

import { useCallback } from "react";

import { formatBytes, stripExtension } from "@/lib/format";
import { getTool, type ToolId } from "@/lib/tools";

import { PageGrid } from "./page-grid";
import { ToolShell } from "./tool-shell";
import { useToolShell } from "./tool-shell-context";
import { useToolPages } from "./use-tool-pages";
import type { ToolRunContext, ToolResult } from "./types";

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

/**
 * Stand-in for the real per-tool processing, which arrives in phases 2 to 5. It walks the
 * same upload-progress then indeterminate path a backend tool will take and hands back the
 * first file untouched, so the whole shell can be exercised before any tool logic exists.
 */
function usePlaceholderProcess(toolId: ToolId) {
  const tool = getTool(toolId);

  return useCallback(
    async ({ files, setProgress, setStage, signal }: ToolRunContext): Promise<ToolResult> => {
      if (tool.runsIn !== "browser") {
        setStage("Uploading");
        for (let percent = 0; percent <= 100; percent += 20) {
          setProgress(percent);
          await delay(120, signal);
        }
      }

      setProgress(null);
      setStage(`Running ${tool.name}`);
      await delay(900, signal);

      const first = files[0];
      return {
        blob: first.file,
        filename: `${stripExtension(first.name)}-${tool.id}.pdf`,
      };
    },
    [tool],
  );
}

/** Tools whose canvas is a page grid rather than a file grid. */
const PAGE_LEVEL_TOOLS: ReadonlySet<ToolId> = new Set(["organize", "split", "page-numbers"]);

/** The page-level canvas, wired to the shared page state so reorder and rotate work. */
function PageCanvas() {
  const { files } = useToolShell();
  const { pages, reorderPages, rotatePage, deletePage } = useToolPages(files);

  return (
    <PageGrid
      pages={pages}
      files={files}
      onReorder={reorderPages}
      onRotate={rotatePage}
      onDelete={deletePage}
    />
  );
}

/** Summary panel standing in for the tool's real options. */
function PlaceholderOptions() {
  const { files, tool } = useToolShell();
  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  const totalPages = files.reduce((sum, file) => sum + (file.pageCount ?? 0), 0);

  return (
    <div className="space-y-4 text-sm">
      <dl className="space-y-2">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Files</dt>
          <dd className="font-medium">{files.length}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Pages</dt>
          <dd className="font-medium">{totalPages || "Reading"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Total size</dt>
          <dd className="font-medium">{formatBytes(totalSize)}</dd>
        </div>
      </dl>

      <p className="rounded-lg border border-dashed border-border p-3 leading-relaxed text-muted-foreground">
        The {tool.name} options land in a later phase. Running it now returns the first file
        unchanged, which is enough to check the shell end to end.
      </p>
    </div>
  );
}

/**
 * Client-only workspace for a tool. Loaded through next/dynamic with `ssr: false` because
 * everything under here touches `crypto.randomUUID`, `File` and canvas at init.
 */
export default function ToolWorkspace({ toolId }: { toolId: ToolId }) {
  const tool = getTool(toolId);
  const process = usePlaceholderProcess(toolId);

  return (
    <ToolShell
      tool={tool}
      process={process}
      info={tool.description}
      options={<PlaceholderOptions />}
      canvas={PAGE_LEVEL_TOOLS.has(toolId) ? <PageCanvas /> : undefined}
    />
  );
}
