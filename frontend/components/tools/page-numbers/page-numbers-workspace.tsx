"use client";

import { useCallback, useState } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFile, ToolResult, ToolRunContext } from "@/components/tool/types";
import { stripExtension } from "@/lib/format";
import { addPageNumbers } from "@/lib/pdf/pageNumbers";
import { zipBlobs, type ZipEntry } from "@/lib/pdf/zip";
import { getTool } from "@/lib/tools";

import { PageNumbersOptions } from "./page-numbers-options";
import { PageNumbersPreview } from "./page-numbers-preview";
import {
  createPageNumbersState,
  planFromState,
  previewFile,
  toPageNumberOptions,
  type PageNumbersState,
} from "./page-numbers-state";

const tool = getTool("page-numbers");

export default function PageNumbersWorkspace() {
  const [state, setState] = useState<PageNumbersState>(createPageNumbersState);

  // The options live out here because `process` needs them, but they are only valid against
  // the page count of a file inside the shell, so the gate is a predicate over that list.
  const canSubmit = useCallback(
    (files: ToolFile[]) =>
      planFromState(state, previewFile(files, state.previewFileId)?.pageCount ?? null).issue ===
      null,
    [state],
  );

  const process = useCallback(
    async ({ files, setProgress, setStage }: ToolRunContext): Promise<ToolResult> => {
      setStage(files.length === 1 ? "Adding the numbers" : `Numbering ${files.length} files`);
      setProgress(0);

      const entries: ZipEntry[] = [];

      for (const [index, file] of files.entries()) {
        // Each file gets the same settings but its own last page, so "to the end" means the
        // end of that document rather than the end of the one being previewed.
        const options = toPageNumberOptions(state, file.pageCount ?? 0);
        entries.push({
          name: `${stripExtension(file.name)}-numbered.pdf`,
          blob: await addPageNumbers(file.file, options),
        });
        setProgress(Math.round(((index + 1) / files.length) * 100));
      }

      if (entries.length === 1) {
        return { blob: entries[0].blob, filename: entries[0].name };
      }

      setProgress(null);
      setStage("Building the ZIP");

      return {
        blob: await zipBlobs(entries),
        filename: "numbered-pdfs.zip",
        downloadLabel: `Download ${entries.length} PDFs`,
      };
    },
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="The red dot on each page is where the number will be printed. Pages that are already sideways get an upright number in the same spot."
      options={<PageNumbersOptions state={state} onChange={setState} />}
      canvas={<PageNumbersPreview state={state} />}
      canSubmit={canSubmit}
    />
  );
}
