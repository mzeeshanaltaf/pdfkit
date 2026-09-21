"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { PdfLoadError } from "@/lib/pdf/load";
import { handOffFiles } from "@/lib/file-handoff";
import { recordRun } from "@/lib/stats/record";
import { getTool, toolHref, type Tool } from "@/lib/tools";
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
import type {
  ToolFile,
  ToolPhase,
  ToolPlacement,
  ToolProcess,
  ToolResult,
  ToolStatus,
} from "./types";
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
  /**
   * Let password-protected files through to `process` instead of treating them as broken.
   * Only Unlock wants this: for every other tool an encrypted file is a dead end, which is
   * what the EncryptedNotice banner is for.
   */
  acceptEncrypted?: boolean;
  /**
   * Files to load as soon as the workspace mounts, e.g. the ones the encrypted-PDF banner
   * handed over on the way to Unlock. Called once.
   */
  adoptFiles?: () => File[];
  /** Rendered inside the shell whatever the phase — used for the Unlock password dialog. */
  overlay?: ReactNode;
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
  acceptEncrypted = false,
  adoptFiles,
  overlay,
}: ToolShellProps) {
  const filesApi = useToolFiles(tool);
  const { files, addFiles, removeFile, reorderFiles, sortFiles, clearFiles } = filesApi;

  // "idle" covers both select and configure: which one shows is just "are there files yet".
  const [phase, setPhase] = useState<ToolPhase>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [stage, setStage] = useState("Working on it");
  const [detail, setDetail] = useState<string | null>(null);
  const [placement, setPlacement] = useState<ToolPlacement | null>(null);
  const [result, setResult] = useState<ToolResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  /** True when the run failed because a file turned out to be encrypted. See `handleSubmit`. */
  const [failedOnPassword, setFailedOnPassword] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const runStartRef = useRef(0);
  /**
   * Mirrors `placement` state, read by `recordRun` calls instead of the state variable.
   * `handleSubmit` is one long-running async closure created at click time; the `placement`
   * it closed over stays whatever it was at creation (always `null`, set right above the
   * `process()` call) no matter how many times `setPlacement` fires while it awaits — state
   * updates never mutate an already-captured closure variable. The ref sidesteps that: it is
   * mutated in place, so the same running closure sees every update.
   */
  const placementRef = useRef<ToolPlacement | null>(null);
  const setPlacementTracked = useCallback((next: ToolPlacement | null) => {
    placementRef.current = next;
    setPlacement(next);
  }, []);

  const { getRootProps, getInputProps, isDragActive, open } = usePdfDropzone({
    tool,
    addFiles,
    noClick: true,
  });

  const status: ToolStatus =
    phase === "idle" ? (files.length === 0 ? "select" : "configure") : phase;

  // Abandon an in-flight run if the user navigates away mid-job.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Files handed over from another tool. A ref keeps this to one adoption even under the
  // double-invoked effects of StrictMode.
  const adoptRef = useRef(adoptFiles);
  const adoptedRef = useRef(false);
  useEffect(() => {
    if (adoptedRef.current) return;
    adoptedRef.current = true;
    const incoming = adoptRef.current?.() ?? [];
    if (incoming.length > 0) addFiles(incoming);
  }, [addFiles]);

  const encryptedFiles = useMemo(
    () => files.filter((file) => file.error?.kind === "encrypted"),
    [files],
  );
  const readableFiles = useMemo(
    () =>
      files.filter(
        (file) => !file.error || (acceptEncrypted && file.error.kind === "encrypted"),
      ),
    [files, acceptEncrypted],
  );
  // An encrypted file never gets a page count, so waiting on one would disable the CTA for
  // good — the only tool that accepts them is the one that can open them.
  const stillLoading = readableFiles.some((file) => !file.error && file.pageCount === null);
  const submittable = typeof canSubmit === "function" ? canSubmit(readableFiles) : canSubmit;

  const handleSubmit = useCallback(async () => {
    const controller = new AbortController();
    abortRef.current = controller;
    runStartRef.current = Date.now();

    const fileCount = readableFiles.length;
    const anyPageCountUnknown = readableFiles.some((file) => file.pageCount === null);
    const pageCount = anyPageCountUnknown
      ? null
      : readableFiles.reduce((sum, file) => sum + (file.pageCount ?? 0), 0);
    const bytesIn = readableFiles.reduce((sum, file) => sum + file.size, 0);
    const durationMs = () => Date.now() - runStartRef.current;

    setPhase("processing");
    setFailedOnPassword(false);
    setProgress(null);
    setStage("Working on it");
    setDetail(null);
    setPlacementTracked(null);
    setErrorMessage(null);

    try {
      const output = await process({
        files: readableFiles,
        setProgress,
        setStage,
        setDetail,
        setPlacement: setPlacementTracked,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setResult(output);
      setPhase("done");
      recordRun({
        tool: tool.id,
        outcome: "done",
        fileCount,
        pageCount,
        bytesIn,
        bytesOut: output.blob.size,
        durationMs: durationMs(),
        placement: placementRef.current,
      });
    } catch (error) {
      if (controller.signal.aborted) return;

      // A recoverable failure — a wrong password, a busy or unreachable server, a file the
      // tool had nothing to do — leaves the workspace exactly as it was. Taking over the
      // screen with a failure page would throw that away, so it is a toast and a step back
      // to the files instead.
      if (error instanceof ApiError && error.recoverable) {
        if (!error.silent) toast.error(error.message);
        setPhase("idle");
        recordRun({
          tool: tool.id,
          outcome: "error",
          fileCount,
          pageCount,
          bytesIn,
          bytesOut: 0,
          durationMs: durationMs(),
          errorCode: error.code,
          placement: placementRef.current,
        });
        return;
      }

      // A PDF with only an owner password opens in pdf.js, so the file list never flags it
      // and the banner never appears; pdf-lib refuses it at write time and it lands here
      // instead. The way out is still Unlock, so the failure screen offers it.
      setFailedOnPassword(error instanceof PdfLoadError && error.kind === "encrypted");
      setErrorMessage(error instanceof Error ? error.message : "Something went wrong.");
      setPhase("error");
      recordRun({
        tool: tool.id,
        outcome: "error",
        fileCount,
        pageCount,
        bytesIn,
        bytesOut: 0,
        durationMs: durationMs(),
        errorCode: error instanceof PdfLoadError ? error.kind : undefined,
        placement: placementRef.current,
      });
    } finally {
      setProgress(null);
      setDetail(null);
    }
  }, [process, readableFiles, tool.id, setPlacementTracked]);

  /**
   * Stop the run and go back to the file list.
   *
   * The phase reset has to happen *here*, not in `handleSubmit`'s catch: that catch
   * returns early on an aborted signal without touching the phase, which was invisible
   * while the only aborts came from unmounting. Leave it to the catch and cancelling
   * strands the UI on the spinner for good.
   *
   * On the server side the batch stops between files — the backend checks whether the
   * client is still there before starting each one.
   */
  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setProgress(null);
    setDetail(null);
    setPhase("idle");

    const anyPageCountUnknown = readableFiles.some((file) => file.pageCount === null);
    recordRun({
      tool: tool.id,
      outcome: "cancelled",
      fileCount: readableFiles.length,
      pageCount: anyPageCountUnknown
        ? null
        : readableFiles.reduce((sum, file) => sum + (file.pageCount ?? 0), 0),
      bytesIn: readableFiles.reduce((sum, file) => sum + file.size, 0),
      bytesOut: 0,
      durationMs: Date.now() - runStartRef.current,
      placement: placementRef.current,
    });
  }, [readableFiles, tool.id]);

  const startOver = useCallback(() => {
    abortRef.current?.abort();
    setResult(null);
    setErrorMessage(null);
    setFailedOnPassword(false);
    clearFiles();
    setPhase("idle");
  }, [clearFiles]);

  const shellValue: ToolShellValue = useMemo(
    () => ({ ...filesApi, tool, status, openFilePicker: open }),
    [filesApi, tool, status, open],
  );

  // The overlay (Unlock's password dialog) has to outlive the phase switch: the prompt is
  // raised *while* the run is in flight, so it cannot live inside the configure screen.
  if (status === "processing") {
    return (
      <>
        <ProcessingView
          progress={progress}
          stage={stage}
          detail={detail}
          onCancel={handleCancel}
          placement={placement}
        />
        {overlay}
      </>
    );
  }

  if (status === "done" && result) {
    return (
      <>
        <ResultView tool={tool} result={result} onStartOver={startOver} placement={placement} />
        {overlay}
      </>
    );
  }

  if (status === "error") {
    return (
      <div
        role="alert"
        className="flex flex-1 flex-col items-center justify-center gap-5 px-4 py-20 text-center"
      >
        <AlertTriangle className="size-9 text-destructive" aria-hidden />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{tool.name} did not finish</h2>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            {errorMessage ?? "Something went wrong."}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          {failedOnPassword && !acceptEncrypted ? (
            <Button asChild>
              <Link
                href={toolHref(getTool("unlock"))}
                onClick={() => handOffFiles(files.map((entry) => entry.file))}
              >
                Remove the password first
              </Link>
            </Button>
          ) : (
            <Button onClick={() => setPhase("idle")}>Back to the files</Button>
          )}
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
          {/* The `main` landmark is the route group's layout; this is just the canvas. */}
          <div
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

            {/* The right gutter is the space the floating add-files button sits in. */}
            <div className="mx-auto max-w-[1100px] space-y-5 pr-14 sm:pr-16">
              {encryptedFiles.length > 0 && !acceptEncrypted && (
                <EncryptedNotice files={encryptedFiles} />
              )}

              {canvas ?? (
                <FileGrid
                  files={files}
                  onRemove={removeFile}
                  onReorder={reorderFiles}
                  renderActions={renderFileActions}
                  allowEncrypted={acceptEncrypted}
                />
              )}
            </div>
          </div>

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
      {overlay}
    </ToolShellProvider>
  );
}
