"use client";

import { useCallback, useState } from "react";

import { numericHeader, runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import { CompressOptions, DEFAULT_COMPRESS_LEVEL, type CompressLevel } from "./compress-options";

const tool = getTool("compress");

export default function CompressWorkspace() {
  const [level, setLevel] = useState<CompressLevel>(DEFAULT_COMPRESS_LEVEL);

  const process = useCallback(
    async (context: ToolRunContext): Promise<ToolResult> => {
      const { blob, filename, headers } = await runBackendTool(
        context,
        "/compress",
        { level },
        { workingStage: "Compressing", fallbackName: "compressed.pdf" },
      );

      // Ghostscript can come back with a bigger file than it was given, in which case the
      // backend returns the original bytes and the two headers are equal — ResultView reads
      // that as "already as small as it gets" rather than claiming a 0% saving.
      return {
        blob,
        filename,
        originalSize: numericHeader(headers, "x-original-size"),
        resultSize: numericHeader(headers, "x-result-size"),
      };
    },
    [level],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Your files are sent to the server, compressed with Ghostscript, and deleted as soon as the result is on its way back."
      options={<CompressOptions level={level} onChange={setLevel} />}
    />
  );
}
