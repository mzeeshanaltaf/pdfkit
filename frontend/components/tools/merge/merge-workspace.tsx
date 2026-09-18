"use client";

import { useCallback } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFile, ToolResult, ToolRunContext } from "@/components/tool/types";
import { mergePdfs } from "@/lib/pdf/merge";
import { getTool } from "@/lib/tools";

import { MergeOptions } from "./merge-options";

const tool = getTool("merge");

/** Merging is only meaningful once there is something to merge with. */
function canMerge(files: ToolFile[]): boolean {
  return files.length >= 2;
}

export default function MergeWorkspace() {
  const process = useCallback(
    async ({ files, setProgress, setStage }: ToolRunContext): Promise<ToolResult> => {
      setStage(`Merging ${files.length} files`);
      setProgress(0);

      const blob = await mergePdfs(
        files.map((file) => file.file),
        (completed, total) => setProgress(Math.round((completed / total) * 100)),
      );

      return { blob, filename: "merged.pdf" };
    },
    [],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Files are merged in the order shown. Drag a card to move it, or sort them by name with the button above the grid."
      options={<MergeOptions />}
      canSubmit={canMerge}
    />
  );
}
