"use client";

import { useCallback } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFile, ToolResult, ToolRunContext } from "@/components/tool/types";
import { stripExtension } from "@/lib/format";
import { rotatePdf } from "@/lib/pdf/rotate";
import { zipBlobs, type ZipEntry } from "@/lib/pdf/zip";
import { getTool } from "@/lib/tools";

import { RotateFileAction } from "./rotate-file-action";
import { RotateOptions } from "./rotate-options";

const tool = getTool("rotate");

/** Running with everything still upright would hand back the input unchanged. */
function hasRotation(files: ToolFile[]): boolean {
  return files.some((file) => file.rotation !== 0);
}

export default function RotateWorkspace() {
  const process = useCallback(
    async ({ files, setProgress, setStage }: ToolRunContext): Promise<ToolResult> => {
      setStage(files.length === 1 ? "Rotating pages" : `Rotating ${files.length} files`);
      setProgress(files.length > 1 ? 0 : null);

      const entries: ZipEntry[] = [];

      for (const [index, file] of files.entries()) {
        entries.push({
          name: `${stripExtension(file.name)}-rotated.pdf`,
          blob: await rotatePdf(file.file, file.rotation),
        });
        if (files.length > 1) {
          setProgress(Math.round(((index + 1) / files.length) * 100));
        }
      }

      if (entries.length === 1) {
        return { blob: entries[0].blob, filename: entries[0].name };
      }

      setProgress(null);
      setStage("Building the ZIP");

      return {
        blob: await zipBlobs(entries),
        filename: "rotated-pdfs.zip",
        downloadLabel: `Download ${entries.length} PDFs`,
      };
    },
    [],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Every page in a file turns together. Hover a card to turn that file on its own."
      options={<RotateOptions />}
      canSubmit={hasRotation}
      renderFileActions={(file) => <RotateFileAction file={file} />}
    />
  );
}
