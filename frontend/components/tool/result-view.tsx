"use client";

import { CheckCircle2, Download, RotateCcw } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { downloadBlob } from "@/lib/download";
import { formatBytes, percentSmaller } from "@/lib/format";
import { ACCENT_TILE_CLASS, relatedTools, type Tool, toolHref } from "@/lib/tools";
import { cn } from "@/lib/utils";

import type { ToolResult } from "./types";

interface ResultViewProps {
  tool: Tool;
  result: ToolResult;
  onStartOver: () => void;
}

export function ResultView({ tool, result, onStartOver }: ResultViewProps) {
  const { originalSize, resultSize } = result;
  const saved =
    originalSize !== undefined && resultSize !== undefined
      ? percentSmaller(originalSize, resultSize)
      : null;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-16 text-center">
      <div>
        <CheckCircle2 className="mx-auto size-10 text-brand" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight md:text-3xl">
          {tool.name} is done
        </h1>
        {saved !== null && (
          <p className="mt-2 text-sm text-muted-foreground">
            {formatBytes(originalSize!)} to {formatBytes(resultSize!)}
            {saved > 0 ? `, ${saved}% smaller` : ", already as small as it gets"}
          </p>
        )}
      </div>

      <div className="flex flex-col items-center gap-3">
        <Button
          size="lg"
          className="h-14 gap-2 px-8 text-base font-semibold"
          onClick={() => downloadBlob(result.blob, result.filename)}
        >
          <Download className="size-5" aria-hidden />
          {result.downloadLabel ?? "Download"}
        </Button>

        <Button variant="ghost" size="sm" onClick={onStartOver}>
          <RotateCcw aria-hidden />
          Start over
        </Button>
      </div>

      <div className="w-full max-w-lg border-t border-border pt-8">
        <h2 className="text-sm font-medium text-muted-foreground">Continue to</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {relatedTools(tool.id).map((next) => {
            const Icon = next.icon;
            return (
              <Link
                key={next.id}
                href={toolHref(next)}
                className="flex items-center gap-2.5 rounded-xl border border-border bg-card p-3 text-left text-sm font-medium transition-colors hover:border-brand/40 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-md",
                    ACCENT_TILE_CLASS[next.accent],
                  )}
                >
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="truncate">{next.name}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
