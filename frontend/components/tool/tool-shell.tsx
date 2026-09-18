"use client";

import { AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { Tool } from "@/lib/tools";
import { cn } from "@/lib/utils";

import { AddFilesButton } from "./add-files-button";
import { EncryptedNotice } from "./encrypted-notice";
import { FileDropzone } from "./file-dropzone";
import { FileGrid } from "./file-grid";
import { OptionsSidebar } from "./options-sidebar";
import { ProcessingView } from "./processing-view";
import { ResultView } from "./result-view";
import { SortButton } from "./sort-button";
import { ToolShellProvider, type ToolShellValue } from "./tool-shell-context";
import type { ToolFile, ToolPhase, ToolProcess, ToolResult, ToolStatus } from "./types";
import { usePdfDropzone } from "./use-pdf-dropzone";
import { useToolFiles } from "./use-tool-files";

interface ToolShellProps {
  tool: Tool;
  /** Does the actual work and returns something downloadable. */
  process: ToolProcess;
  /** Body of the right-hand sidebar. Rendered inside the provider, so it can useToolShell(). */
  options?: ReactNode;
  /** Short note at the top of the sidebar. */
  info?: ReactNode;
  /** Replaces the default file grid, e.g. with a PageGrid for Organize. */
  canvas?: ReactNode;
  /**
   * Extra gate on the CTA, on top of "at least one readable file". A predicate form is
   * given the readable files, which is how Merge asks for two of them and Split checks its
   * ranges against the real page count without lifting the file list out of the shell.
   */
  canSubmit?: boolean | ((files: ToolFile[]) => boolean);
  /** Per-card hover controls in the default file grid. */
  renderFileActions?: (file: ToolFile) => ReactNode;
}

/**
 * The frame every tool page is built on. It owns the select to configure to processing to
 * done or error state machine, the file list, and the two-column layout: canvas on the left,
 * fixed-width options sidebar on the right that stacks underneath below `lg`.
 */
export function ToolShell({
  tool,
  process,
  options,
  info,
  canvas,
  canSubmit = true,
  renderFileActions,
}: ToolShellProps) {
  const filesApi = useToolFiles(tool);
  const { files, addFiles, removeFile, reorderFiles, sortFiles, clearFiles } = filesApi;

  // "idle" covers both select and configure: which one shows is just "are there files yet".
  const [phase, setPhase] = useState<ToolPhase>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [stage, setStage] = useState("Working on it");
  const [result, setResult] = useState<ToolResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { getRootProps, getInputProps, isDragActive, open } = usePdfDropzone({
    tool,
    addFiles,
    noClick: true,
  });

  const status: ToolStatus =
    phase === "idle" ? (files.length === 0 ? "select" : "configure") : phase;

  // Abandon an in-flight run if the user navigates away mid-job.
  useEffect(() => () => abortRef.current?.abort(), []);

  const encryptedFiles = useMemo(
    () => files.filter((file) => file.error?.kind === "encrypted"),
    [files],
  );
  const readableFiles = useMemo(() => files.filter((file) => !file.error), [files]);
  const stillLoading = readableFiles.some((file) => file.pageCount === null);
  const submittable = typeof canSubmit === "function" ? canSubmit(readableFiles) : canSubmit;

  const handleSubmit = useCallback(async () => {
    const controller = new AbortController();
    abortRef.current = controller;

    setPhase("processing");
    setProgress(null);
    setStage("Working on it");
    setErrorMessage(null);

    try {
      const output = await process({
        files: readableFiles,
        setProgress,
        setStage,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setResult(output);
      setPhase("done");
    } catch (error) {
      if (controller.signal.aborted) return;
      setErrorMessage(error instanceof Error ? error.message : "Something went wrong.");
      setPhase("error");
    } finally {
      setProgress(null);
    }
  }, [process, readableFiles]);

  const startOver = useCallback(() => {
    abortRef.current?.abort();
    setResult(null);
    setErrorMessage(null);
    clearFiles();
    setPhase("idle");
  }, [clearFiles]);

  const shellValue: ToolShellValue = useMemo(
    () => ({ ...filesApi, tool, status, openFilePicker: open }),
    [filesApi, tool, status, open],
  );

  if (status === "processing") {
    return <ProcessingView progress={progress} stage={stage} />;
  }

  if (status === "done" && result) {
    return <ResultView tool={tool} result={result} onStartOver={startOver} />;
  }

  if (status === "error") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-5 px-4 py-20 text-center">
        <AlertTriangle className="size-9 text-destructive" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{tool.name} did not finish</h1>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">{errorMessage}</p>
        </div>
        <div className="flex gap-3">
          <Button onClick={() => setPhase("idle")}>Back to the files</Button>
          <Button variant="ghost" onClick={startOver}>
            Start over
          </Button>
        </div>
      </div>
    );
  }

  return (
    <ToolShellProvider value={shellValue}>
      {status === "select" ? (
        <FileDropzone tool={tool} addFiles={addFiles} />
      ) : (
        <div className="flex flex-1 flex-col lg:flex-row">
          <main
            {...getRootProps({
              className: cn(
                "relative flex-1 bg-muted/40 px-4 py-6 transition-colors sm:px-6 lg:h-[calc(100dvh-4rem)] lg:overflow-y-auto",
                isDragActive && "bg-brand/5 ring-2 ring-brand/40 ring-inset",
              ),
            })}
          >
            <input {...getInputProps()} />

            <div className="absolute top-6 right-4 z-10 flex flex-col items-center gap-2 sm:right-6">
              <AddFilesButton
                count={files.length}
                onClick={open}
                label={tool.multiple ? "Add more files" : "Replace the file"}
              />
              {tool.multiple && files.length > 1 && <SortButton onSort={sortFiles} />}
            </div>

            <div className="mx-auto max-w-[1100px] space-y-5 pr-16">
              {encryptedFiles.length > 0 && tool.id !== "unlock" && (
                <EncryptedNotice filenames={encryptedFiles.map((file) => file.name)} />
              )}

              {canvas ?? (
                <FileGrid
                  files={files}
                  onRemove={removeFile}
                  onReorder={reorderFiles}
                  renderActions={renderFileActions}
                />
              )}
            </div>
          </main>

          <OptionsSidebar
            title={tool.name}
            info={info}
            ctaLabel={tool.ctaLabel}
            ctaDisabled={!submittable || readableFiles.length === 0 || stillLoading}
            onSubmit={handleSubmit}
          >
            {options}
          </OptionsSidebar>
        </div>
      )}
    </ToolShellProvider>
  );
}
