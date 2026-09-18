"use client";

import dynamic from "next/dynamic";

import type { ToolId } from "@/lib/tools";

/**
 * Every tool workspace is client-only: it reads File objects, renders to canvas and mints
 * ids with `crypto.randomUUID()` while building its initial state, none of which can be
 * server-rendered without a hydration mismatch. `ssr: false` is only allowed inside a
 * Client Component, which is why this thin wrapper exists between the route and the shell.
 */
const ToolWorkspace = dynamic(() => import("./tool-workspace"), {
  ssr: false,
  loading: () => <WorkspaceFallback />,
});

function WorkspaceFallback() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="h-72 w-full max-w-xl animate-pulse rounded-xl bg-muted" aria-hidden />
      <span className="sr-only">Loading the workspace</span>
    </div>
  );
}

export function ToolPage({ toolId }: { toolId: ToolId }) {
  return <ToolWorkspace toolId={toolId} />;
}
