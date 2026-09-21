"use client";

import { useCallback } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { toast } from "sonner";

import type { Tool } from "@/lib/tools";

import type { AddFilesResult } from "./use-tool-files";

interface Options {
  tool: Tool;
  addFiles: (files: File[]) => AddFilesResult;
  /** True for the canvas dropzone, where clicking a file card must not open the picker. */
  noClick?: boolean;
}

function describeRejection(rejection: FileRejection, tool: Tool): string {
  const code = rejection.errors[0]?.code;
  if (code === "file-invalid-type") return `${rejection.file.name} is not a PDF.`;
  if (code === "too-many-files") return `${tool.name} takes one file at a time.`;
  return rejection.errors[0]?.message ?? `${rejection.file.name} could not be added.`;
}

/**
 * Shared drag-and-drop wiring. The select screen and the file canvas both use it, so the
 * same extension, multiplicity and size rules apply however a file arrives.
 */
export function usePdfDropzone({ tool, addFiles, noClick = false }: Options) {
  const onDrop = useCallback(
    (accepted: File[], rejections: FileRejection[]) => {
      const messages = rejections.map((rejection) => describeRejection(rejection, tool));
      let warning: string | undefined;
      if (accepted.length > 0) {
        const result = addFiles(accepted);
        messages.push(...result.rejected);
        warning = result.warning;
      }
      // Three is enough to explain what happened without burying the screen in toasts.
      for (const message of messages.slice(0, 3)) toast.error(message);
      if (warning) toast.warning(warning);
    },
    [addFiles, tool],
  );

  return useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: tool.multiple,
    noClick,
    noKeyboard: noClick,
  });
}
