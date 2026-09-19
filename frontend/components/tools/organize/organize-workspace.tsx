"use client";

import { useCallback, useState } from "react";

import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolFile, ToolResult, ToolRunContext } from "@/components/tool/types";
import { stripExtension } from "@/lib/format";
import { organizePdf } from "@/lib/pdf/organize";
import { getTool } from "@/lib/tools";

import { OrganizeCanvas } from "./organize-canvas";
import { OrganizeOptions } from "./organize-options";
import {
  createOrganizeState,
  syncOrganize,
  toOrganizeItems,
  toOrganizeSources,
  type OrganizeState,
} from "./organize-state";

const tool = getTool("organize");

export default function OrganizeWorkspace() {
  const [state, setState] = useState<OrganizeState>(createOrganizeState);

  // The grid lives out here because `process` is what turns it into a document, so the CTA
  // gate has to re-derive it against the file list the shell is holding.
  const canSubmit = useCallback(
    (files: ToolFile[]) => syncOrganize(state, files).pages.length > 0,
    [state],
  );

  const process = useCallback(
    async ({ files, setProgress, setStage }: ToolRunContext): Promise<ToolResult> => {
      const pages = syncOrganize(state, files).pages;

      setStage("Building the document");
      setProgress(0);

      const blob = await organizePdf(
        toOrganizeItems(pages),
        toOrganizeSources(files),
        (completed, total) => setProgress(Math.round((completed / total) * 100)),
      );

      return { blob, filename: `${stripExtension(files[0].name)}-organized.pdf` };
    },
    [state],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="Every page of every file you add lands in one grid. Drag them into the order you want, then build the new document."
      options={<OrganizeOptions state={state} onChange={setState} />}
      canvas={<OrganizeCanvas state={state} onChange={setState} />}
      canSubmit={canSubmit}
    />
  );
}
