"use client";

import { Cloud, Server } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import type { ToolPlacement } from "./types";

interface PlacementBadgeProps {
  placement: ToolPlacement | null;
  /** Present tense while the job is running, past tense once it is done. */
  tense: "running" | "done";
  className?: string;
}

const LABEL: Record<ToolPlacement, Record<PlacementBadgeProps["tense"], string>> = {
  server: {
    running: "Running on our server",
    done: "Processed on our server",
  },
  sandbox: {
    running: "Running in a secure cloud sandbox",
    done: "Processed in a secure cloud sandbox",
  },
};

/**
 * Shared by ProcessingView and ResultView. A visible label that showed up for "sandbox"
 * and nothing at all for "server" read as a glitch — why does this message appear
 * sometimes and not others? An icon for both placements makes the split legible instead:
 * cloud for a Daytona sandbox, server for the VPS. The full explanation lives in each
 * offload-capable tool's FAQ, so this stays a tooltip rather than permanent copy. Renders
 * nothing for `null` (browser tools, or a backend tool that hasn't said yet).
 */
export function PlacementBadge({ placement, tense, className }: PlacementBadgeProps) {
  if (placement === null) return null;

  const Icon = placement === "sandbox" ? Cloud : Server;
  const label = LABEL[placement][tense];

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex size-7 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground",
              className,
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            <span className="sr-only">{label}</span>
          </span>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
