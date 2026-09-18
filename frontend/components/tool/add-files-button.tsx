"use client";

import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

interface AddFilesButtonProps {
  count: number;
  onClick: () => void;
  label?: string;
}

/** Floating "+" over the canvas, badged with how many files are loaded. */
export function AddFilesButton({ count, onClick, label = "Add more files" }: AddFilesButtonProps) {
  return (
    <div className="relative">
      <Button
        size="icon-lg"
        className="size-11 rounded-full shadow-lg"
        aria-label={label}
        onClick={onClick}
      >
        <Plus className="size-5" aria-hidden />
      </Button>
      {count > 0 && (
        <span
          className="pointer-events-none absolute -top-1.5 -right-1.5 flex min-w-5 items-center justify-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold text-background"
          aria-hidden
        >
          {count}
        </span>
      )}
    </div>
  );
}
