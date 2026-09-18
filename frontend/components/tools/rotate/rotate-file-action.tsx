"use client";

import { RotateCw } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";
import type { ToolFile } from "@/components/tool/types";

/**
 * The per-file turn button that appears over a card on hover. It reads the file list from
 * the shell context rather than taking a callback, because `renderFileActions` runs inside
 * the provider and threading a handler down through the grid buys nothing.
 */
export function RotateFileAction({ file }: { file: ToolFile }) {
  const { rotateFile } = useToolShell();

  return (
    <Button
      variant="secondary"
      size="icon-xs"
      aria-label={`Rotate ${file.name} right, currently ${file.rotation} degrees`}
      onClick={() => rotateFile(file.id, 90)}
    >
      <RotateCw aria-hidden />
    </Button>
  );
}
