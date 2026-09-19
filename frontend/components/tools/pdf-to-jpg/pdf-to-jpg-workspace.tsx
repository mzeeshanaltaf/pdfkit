"use client";

import { useCallback, useState } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { pdfToJpg } from "@/lib/pdf/pdfToJpg";
import { getTool } from "@/lib/tools";

import { createJpgState, PdfToJpgOptions, type JpgState } from "./pdf-to-jpg-options";

const tool = getTool("pdf-to-jpg");

export default function PdfToJpgWorkspace() {
  const [state, setState] = useState<JpgState>(createJpgState);

  const process = useCallback(
    async ({ files, setProgress, setStage, signal }: ToolRunContext): Promise<ToolResult> => {
      setStage("Rendering the pages");
      setProgress(0);

      const { blob, filename, imageCount } = await pdfToJpg(
        files.map((file) => ({ id: file.id, name: file.name, file: file.file })),
        {
          quality: state.quality,
          signal,
          onProgress: (completed, total) => {
            setProgress(Math.round((completed / total) * 100));
            // The ZIP is built after the last page, and on a long document that pause is
            // long enough to need saying out loud.
            if (completed === total && total > 1) {
              setProgress(null);
              setStage("Building the ZIP");
            }
          },
        },
      );

      return {
        blob,
        filename,
        downloadLabel: imageCount > 1 ? `Download ${imageCount} JPG images` : undefined,
      };
    },
    [state.quality],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Each page is rendered to an image in your browser. Several pages come back as a ZIP."
      options={<PdfToJpgOptions state={state} onChange={setState} />}
    />
  );
}
