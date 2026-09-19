"use client";

import { useCallback } from "react";

import { usePasswordPrompt } from "@/components/tool/password-dialog";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { uploadWithPassword, type ApiFileResponse } from "@/lib/api";
import { takeHandedOffFiles } from "@/lib/file-handoff";
import { zipBlobs } from "@/lib/pdf/zip";
import { getTool } from "@/lib/tools";

import { UnlockOptions } from "./unlock-options";

const tool = getTool("unlock");

export default function UnlockWorkspace() {
  const { requestPassword, dismissPrompt, passwordDialog } = usePasswordPrompt();

  const process = useCallback(
    async ({ files, setProgress, setStage, signal }: ToolRunContext): Promise<ToolResult> => {
      // One request per file rather than one for the batch: the backend takes a single
      // password per request, and a batch of differently-locked files would fail whole at
      // the first one. Per file, each gets its own prompt and its own second chance.
      const results: ApiFileResponse[] = [];

      try {
        for (const [index, entry] of files.entries()) {
          const position = files.length === 1 ? "" : ` ${index + 1} of ${files.length}`;
          setStage(`Uploading file${position}`);
          setProgress(Math.round((index / files.length) * 100));

          const result = await uploadWithPassword(
            "/unlock",
            entry.file,
            {},
            {
              signal,
              requestPassword,
              fallbackName: "unlocked.pdf",
              onProgress: (percent) => {
                if (percent >= 100) {
                  // qpdf is working on this one; the next file's upload flips the bar back.
                  setProgress(null);
                  setStage(`Removing the password${position}`);
                } else {
                  // Each file owns its slice of the bar, so a five-file run still moves.
                  setProgress(Math.round(((index + percent / 100) / files.length) * 100));
                }
              },
            },
          );
          results.push(result);
        }
      } finally {
        dismissPrompt();
      }

      if (results.length === 1) {
        return { blob: results[0].blob, filename: results[0].filename };
      }

      setProgress(null);
      setStage("Building the ZIP");
      const blob = await zipBlobs(
        results.map((result) => ({ name: result.filename, blob: result.blob })),
      );
      return {
        blob,
        filename: "pdfkit-unlocked.zip",
        downloadLabel: `Download ${results.length} unlocked PDFs`,
      };
    },
    [requestPassword, dismissPrompt],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Removing a password needs the password. This only strips protection from a file you can already open."
      options={<UnlockOptions />}
      // The whole point of the tool is the files every other tool refuses.
      acceptEncrypted
      adoptFiles={takeHandedOffFiles}
      overlay={passwordDialog}
    />
  );
}
