"use client";

import { createContext, useContext } from "react";

import type { Tool } from "@/lib/tools";

import type { ToolStatus } from "./types";
import type { ToolFilesApi } from "./use-tool-files";

export interface ToolShellValue extends ToolFilesApi {
  tool: Tool;
  status: ToolStatus;
  /** Opens the native file picker, same validation path as a drop. */
  openFilePicker: () => void;
}

const ToolShellContext = createContext<ToolShellValue | null>(null);

export const ToolShellProvider = ToolShellContext.Provider;

/**
 * Lets a tool options panel read and mutate the workspace file list without ToolShell
 * having to thread a dozen props through every tool.
 */
export function useToolShell(): ToolShellValue {
  const value = useContext(ToolShellContext);
  if (!value) throw new Error("useToolShell must be used inside a ToolShell.");
  return value;
}
