"use client";

import { Loader2 } from "lucide-react";

import { Progress } from "@/components/ui/progress";

interface ProcessingViewProps {
  /** 0-100 while a file is uploading, or null once the work is server-side or in-browser. */
  progress: number | null;
  stage: string;
}

export function ProcessingView({ progress, stage }: ProcessingViewProps) {
  const uploading = progress !== null;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-20 text-center">
      <Loader2 className="size-8 animate-spin text-brand" aria-hidden />

      <div className="w-full max-w-sm">
        <p aria-live="polite" className="text-lg font-medium tracking-tight">
          {stage}
        </p>

        {uploading ? (
          <>
            <Progress value={progress} className="mt-4 h-1.5" />
            <p className="mt-2 text-sm text-muted-foreground">{Math.round(progress)}%</p>
          </>
        ) : (
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            {/* Indeterminate: the work is running and there is no honest percentage to show. */}
            <div className="h-full w-1/3 animate-[pulse_1.4s_ease-in-out_infinite] rounded-full bg-brand" />
          </div>
        )}
      </div>
    </div>
  );
}
