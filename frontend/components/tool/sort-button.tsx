"use client";

import { ArrowDownAZ, ArrowDownZA } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import type { SortDirection } from "./use-tool-files";

/** Toggles the file list between A to Z and Z to A. */
export function SortButton({ onSort }: { onSort: (direction: SortDirection) => void }) {
  const [direction, setDirection] = useState<SortDirection>("asc");

  function handleClick() {
    onSort(direction);
    setDirection(direction === "asc" ? "desc" : "asc");
  }

  return (
    <Button
      variant="outline"
      size="icon-lg"
      className="size-10 rounded-full bg-background shadow-md"
      aria-label={direction === "asc" ? "Sort files A to Z" : "Sort files Z to A"}
      onClick={handleClick}
    >
      {direction === "asc" ? <ArrowDownAZ aria-hidden /> : <ArrowDownZA aria-hidden />}
    </Button>
  );
}
