"use client";

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

interface ProcessingViewProps {
  /** 0-100 for a real measured percentage, or null for an indeterminate wait. */
  progress: number | null;
  stage: string;
  /** Which file of how many, and its name. Null when there is nothing extra to say. */
  detail?: string | null;
  /** Omitted by a tool with nothing to cancel — the button is then not rendered. */
  onCancel?: () => void;
}

export function ProcessingView({ progress, stage, detail, onCancel }: ProcessingViewProps) {
  const measured = progress !== null;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-20 text-center">
      <Loader2 className="size-8 animate-spin text-brand" aria-hidden />

      <div className="w-full max-w-sm">
        <p aria-live="polite" className="text-lg font-medium tracking-tight">
          {stage}
        </p>

        {measured ? (
          <>
            <Progress value={progress} className="mt-4 h-1.5" />
            <p className="mt-2 text-sm text-muted-foreground">{Math.round(progress)}%</p>
          </>
        ) : (
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            {/* Indeterminate: the work is running and there is no honest percentage. */}
            <div className="h-full w-1/3 animate-[pulse_1.4s_ease-in-out_infinite] rounded-full bg-brand" />
          </div>
        )}

        {/* Always rendered so the block below the bar does not jump as the detail
            line comes and goes between files. */}
        <p
          aria-live="polite"
          className="mt-2 min-h-5 text-sm text-muted-foreground"
        >
          {detail ?? ""}
        </p>

        {onCancel && (
          <Button variant="ghost" size="sm" className="mt-4" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}
