"use client";

import { useCallback, useState } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFile, ToolResult, ToolRunContext } from "@/components/tool/types";
import { splitPdf } from "@/lib/pdf/split";
import { getTool } from "@/lib/tools";

import { SplitOptions } from "./split-options";
import { SplitPreview } from "./split-preview";
import { createSplitState, planFromState, toSplitInput, type SplitState } from "./split-state";

const tool = getTool("split");

export default function SplitWorkspace() {
  const [state, setState] = useState<SplitState>(createSplitState);

  // The options live out here because `process` needs them, but they are only valid against
  // the page count of the file inside the shell, so the gate is a predicate over that list.
  const canSubmit = useCallback(
    (files: ToolFile[]) => planFromState(state, files[0]?.pageCount ?? null).issue === null,
    [state],
  );

  const process = useCallback(
    async ({ files, setProgress, setStage }: ToolRunContext): Promise<ToolResult> => {
      const file = files[0];
      const pageCount = file.pageCount ?? 0;

      setStage("Splitting the document");
      setProgress(0);

      const { blob, filename, documentCount } = await splitPdf(
        file.file,
        toSplitInput(state, pageCount),
        (completed, total) => setProgress(Math.round((completed / total) * 100)),
      );

      return {
        blob,
        filename,
        downloadLabel: documentCount > 1 ? `Download ${documentCount} PDFs` : undefined,
      };
    },
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Cut the document into ranges, or pull out just the pages you name. Several pieces come back as a ZIP."
      options={<SplitOptions state={state} onChange={setState} />}
      canvas={<SplitPreview state={state} />}
      canSubmit={canSubmit}
    />
  );
}
