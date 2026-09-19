"use client";

import { useCallback, useState } from "react";

import { runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import {
  createWordState,
  PdfToWordOptions,
  wordReady,
  type WordState,
} from "./pdf-to-word-options";

const tool = getTool("pdf-to-word");

export default function PdfToWordWorkspace() {
  const [state, setState] = useState<WordState>(createWordState);

  const process = useCallback(
    async (context: ToolRunContext): Promise<ToolResult> => {
      const { blob, filename } = await runBackendTool(
        context,
        "/convert/word",
        { ocr: state.mode, languages: state.languages.join(",") },
        {
          // With OCR on, the wait is recognition plus layout rebuilding, and on a
          // long scan that is minutes — worth saying, rather than leaving a spinner
          // to imply a hang.
          workingStage:
            state.mode === "auto"
              ? "Reading the pages, then rebuilding the document"
              : "Rebuilding the document",
          fallbackName: "document.docx",
        },
      );
      return { blob, filename };
    },
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Your file is sent to the server, rebuilt as a Word document, and deleted as soon as the result is on its way back."
      options={<PdfToWordOptions state={state} onChange={setState} />}
      canSubmit={wordReady(state)}
    />
  );
}
