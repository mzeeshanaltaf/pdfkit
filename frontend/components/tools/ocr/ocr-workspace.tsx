"use client";

import { useCallback, useMemo, useState } from "react";

import { runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import { OcrOptions } from "./ocr-options";
import { useOcrLanguages } from "./use-ocr-languages";

const tool = getTool("ocr");

export default function OcrWorkspace() {
  const { languages, loading } = useOcrLanguages();
  const [selected, setSelected] = useState<string[]>(["eng"]);

  // The default is English because the backend's is, but which models are installed is the
  // image's business. A code this server does not have would come back as a 400, so the
  // selection is filtered against the real list — derived, not written back into state.
  // Filtering to nothing simply disables the CTA, and the panel says why.
  const chosen = useMemo(() => {
    const installed = new Set(languages.map((entry) => entry.code));
    return selected.filter((code) => installed.has(code));
  }, [languages, selected]);

  const process = useCallback(
    async (context: ToolRunContext): Promise<ToolResult> => {
      const { blob, filename } = await runBackendTool(
        context,
        "/ocr",
        { languages: chosen.join(",") },
        {
          // OCR is the slow one — minutes on a long scan — so the stage text says what is
          // happening rather than leaving a bare spinner to imply a hang.
          workingStage: "Reading the pages — this is the slow part",
          fallbackName: "ocr.pdf",
        },
      );
      return { blob, filename };
    },
    [chosen],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Your scan is sent to the server, read with Tesseract, and comes back with a selectable, searchable text layer behind the original image."
      options={
        <OcrOptions
          languages={languages}
          loading={loading}
          selected={chosen}
          onChange={setSelected}
        />
      }
      canSubmit={chosen.length > 0}
    />
  );
}
