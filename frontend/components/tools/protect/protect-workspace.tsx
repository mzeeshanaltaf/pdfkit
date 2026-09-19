"use client";

import { useCallback, useState } from "react";

import { runBackendTool } from "@/components/tool/backend-run";
import { ToolShell } from "@/components/tool/tool-shell";
import type { ToolResult, ToolRunContext } from "@/components/tool/types";
import { getTool } from "@/lib/tools";

import {
  createProtectState,
  ProtectOptions,
  protectReady,
  type ProtectState,
} from "./protect-options";

const tool = getTool("protect");

export default function ProtectWorkspace() {
  const [state, setState] = useState<ProtectState>(createProtectState);

  const process = useCallback(
    async (context: ToolRunContext): Promise<ToolResult> => {
      const { blob, filename } = await runBackendTool(
        context,
        "/protect",
        { password: state.password },
        { workingStage: "Encrypting", fallbackName: "protected.pdf" },
      );
      return { blob, filename };
    },
    [state.password],
  );

  return (
    <ToolShell
      tool={tool}
      process={process}
      info="The password encrypts the file on the server with AES-256. It is used for this one request and never written down."
      options={<ProtectOptions state={state} onChange={setState} />}
      canSubmit={protectReady(state)}
    />
  );
}
