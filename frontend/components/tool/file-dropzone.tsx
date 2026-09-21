"use client";

import { FilePlus2, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { MAX_BATCH_LABEL, MAX_FILES_PER_BATCH, MAX_UPLOAD_LABEL } from "@/lib/constants";
import type { Tool } from "@/lib/tools";
import { cn } from "@/lib/utils";

import { usePdfDropzone } from "./use-pdf-dropzone";
import type { AddFilesResult } from "./use-tool-files";

interface FileDropzoneProps {
  tool: Tool;
  addFiles: (files: File[]) => AddFilesResult;
}

/** The first screen of every tool: one big target that also accepts a drop anywhere on it. */
export function FileDropzone({ tool, addFiles }: FileDropzoneProps) {
  const { getRootProps, getInputProps, isDragActive, open } = usePdfDropzone({
    tool,
    addFiles,
    noClick: true,
  });

  return (
    <div
      {...getRootProps({
        className: cn(
          "flex flex-1 items-center justify-center px-4 py-12 transition-colors",
          isDragActive && "bg-brand/5",
        ),
      })}
    >
      <input {...getInputProps()} />

      <div
        className={cn(
          "flex w-full max-w-xl flex-col items-center rounded-xl border-2 border-dashed border-border px-4 py-10 text-center transition-colors sm:px-6 sm:py-14",
          isDragActive && "border-brand bg-brand/5",
        )}
      >
        <span className="flex size-12 items-center justify-center rounded-lg bg-brand/10 text-brand">
          {isDragActive ? <UploadCloud aria-hidden /> : <FilePlus2 aria-hidden />}
        </span>

        {/*
          The workspace heading, not a restatement of the button below it. An `h2`, not an
          `h1`: the route's single `h1` is the server-rendered one in `ToolSeoSection`, which
          is the only heading a crawler sees at all — this whole tree is `ssr: false`.
        */}
        <h2 className="mt-5 text-xl font-semibold tracking-tight">{tool.name}</h2>
        <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
          {tool.description}
        </p>

        <Button
          size="lg"
          className="mt-6 h-11 px-6 text-base"
          onClick={open}
          type="button"
        >
          {tool.multiple ? "Select PDF files" : "Select PDF file"}
        </Button>

        <p className="mt-4 text-xs text-muted-foreground">
          or drop {tool.multiple ? "them" : "it"} here
          {tool.runsIn === "browser"
            ? null
            : tool.multiple
              ? `, up to ${MAX_UPLOAD_LABEL} per file (${MAX_FILES_PER_BATCH} files, ${MAX_BATCH_LABEL} per batch)`
              : `, up to ${MAX_UPLOAD_LABEL} per file`}
        </p>
      </div>
    </div>
  );
}
