"use client";

import { Cloud } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { ToolPlacement } from "./types";

interface PlacementBadgeProps {
  placement: ToolPlacement | null;
  /** Present tense while the job is running, past tense once it is done. */
  tense: "running" | "done";
  className?: string;
}

/**
 * Shared by ProcessingView and ResultView. Nothing at all for `"server"` or `null`: the
 * VPS is the unremarkable default, and a badge for it would be noise on ten of the
 * twelve tools — this only ever shows up for the four that can offload. Renders nothing
 * (not even a wrapper), so a caller's own spacing never has to account for an empty node.
 */
export function PlacementBadge({ placement, tense, className }: PlacementBadgeProps) {
  if (placement !== "sandbox") return null;

  return (
    <Badge variant="secondary" className={cn("gap-1.5", className)}>
      <Cloud className="size-3.5" aria-hidden />
      {tense === "running"
        ? "Running in a secure cloud sandbox"
        : "Processed in a secure cloud sandbox"}
    </Badge>
  );
}
