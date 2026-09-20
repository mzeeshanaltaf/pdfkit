"use client";

import { useCallback, useState } from "react";

import { numericHeader, runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFileStat, ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import { CompressOptions, DEFAULT_COMPRESS_LEVEL, type CompressLevel } from "./compress-options";

const tool = getTool("compress");

/** Sent only for a multi-file batch — absent (and safe to no-op) for a single file. */
function parseFileStats(raw: string | undefined): ToolFileStat[] | undefined {
  if (!raw) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return undefined;
    return parsed as ToolFileStat[];
  } catch {
    return undefined;
  }
}

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

      // When neither compression route beats the upload, the backend returns the original
      // bytes and the two headers come back equal — ResultView reads that as "already as
      // small as it gets" rather than claiming a 0% saving.
      return {
        blob,
        filename,
        originalSize: numericHeader(headers, "x-original-size"),
        resultSize: numericHeader(headers, "x-result-size"),
        fileStats: parseFileStats(headers["x-file-stats"]),
      };
    },
    [level],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Your files are sent to the server, compressed, and deleted as soon as the result is on its way back."
      options={<CompressOptions level={level} onChange={setLevel} />}
    />
  );
}
