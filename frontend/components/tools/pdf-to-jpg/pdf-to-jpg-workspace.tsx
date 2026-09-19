"use client";

import { useCallback, useState } from "react";

import { runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { pdfToJpg } from "@/lib/pdf/pdfToJpg";
import { getTool } from "@/lib/tools";

import { createJpgState, PdfToJpgOptions, type JpgState } from "./pdf-to-jpg-options";

const tool = getTool("pdf-to-jpg");

/** Renders each page to an image, entirely in the browser. */
async function renderPages(
  { files, setProgress, setStage, signal }: ToolRunContext,
  state: JpgState,
): Promise<ToolResult> {
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
}

/** Pulls the bitmaps the document already contains, which needs poppler on the server. */
async function extractImages(context: ToolRunContext, state: JpgState): Promise<ToolResult> {
  const { blob, filename } = await runBackendTool(
    context,
    "/images/extract",
    { quality: state.quality },
    { workingStage: "Looking for embedded images", fallbackName: "images.zip" },
  );
  return { blob, filename, downloadLabel: "Download the images" };
}

export default function PdfToJpgWorkspace() {
  const [state, setState] = useState<JpgState>(createJpgState);

  const process = useCallback(
    (context: ToolRunContext): Promise<ToolResult> =>
      state.mode === "extract" ? extractImages(context, state) : renderPages(context, state),
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info={
        state.mode === "extract"
          ? "Extraction reads the document's own image streams on the server, so it returns the originals rather than a re-render of the page."
          : "Each page is rendered to an image in your browser. Several pages come back as a ZIP."
      }
      options={<PdfToJpgOptions state={state} onChange={setState} />}
    />
  );
}
