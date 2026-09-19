"use client";

import { useCallback, useState } from "react";

import { runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import {
  createMarkdownState,
  markdownReady,
  PdfToMarkdownOptions,
  type MarkdownState,
} from "./pdf-to-markdown-options";

const tool = getTool("pdf-to-markdown");

export default function PdfToMarkdownWorkspace() {
  const [state, setState] = useState<MarkdownState>(createMarkdownState);

  const process = useCallback(
    async (context: ToolRunContext): Promise<ToolResult> => {
      const { blob, filename } = await runBackendTool(
        context,
        "/convert/markdown",
        { ocr: state.mode, languages: state.languages.join(",") },
        {
          workingStage: "Reading the document",
          fallbackName: "document.md",
        },
      );
      return {
        blob,
        filename,
        downloadLabel: context.files.length > 1 ? "Download the Markdown" : undefined,
      };
    },
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Your file is sent to the server, converted to Markdown, and deleted as soon as the result is on its way back."
      options={<PdfToMarkdownOptions state={state} onChange={setState} />}
      canSubmit={markdownReady(state)}
    />
  );
}
