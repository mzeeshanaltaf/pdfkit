"use client";

import { uploadAndProcess, type ApiFileResponse } from "@/lib/api";

import type { ToolRunContext } from "./types";

interface BackendRunOptions {
  /** Stage text for the part of the job that happens on the server. */
  workingStage: string;
  /** Download name to fall back on if the response carries no Content-Disposition. */
  fallbackName: string;
}

/**
 * The shared shape of a backend tool's run: a real upload percentage, then an indeterminate
 * wait while the server works. Once the last byte is on the wire there is nothing honest
 * left to put a number on, so the bar switches to indeterminate rather than sitting at 100%
 * pretending the job is nearly done.
 */
export function runBackendTool(
  { files, setProgress, setStage, signal }: ToolRunContext,
  endpoint: string,
  fields: Record<string, string>,
  { workingStage, fallbackName }: BackendRunOptions,
): Promise<ApiFileResponse> {
  setStage(files.length === 1 ? "Uploading your file" : `Uploading ${files.length} files`);
  setProgress(0);

  return uploadAndProcess(
    endpoint,
    files.map((file) => file.file),
    fields,
    {
      signal,
      fallbackName,
      onProgress: (percent) => {
        if (percent >= 100) {
          setProgress(null);
          setStage(workingStage);
        } else {
          setProgress(percent);
        }
      },
    },
  );
}

/** Reads a numeric response header, or undefined when it is missing or not a number. */
export function numericHeader(
  headers: Record<string, string>,
  name: string,
): number | undefined {
  const value = Number(headers[name]);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}
