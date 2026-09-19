"use client";

import dynamic from "next/dynamic";
import type { ComponentType } from "react";

import type { ToolId } from "@/lib/tools";

/**
 * Every tool workspace is client-only: it reads File objects, renders to canvas and mints
 * ids with `crypto.randomUUID()` while building its initial state, none of which can be
 * server-rendered without a hydration mismatch. `ssr: false` is only allowed inside a
 * Client Component, which is why this thin wrapper exists between the route and the shell.
 *
 * Declaring one lazy component per tool also keeps them in separate chunks: a visit to
 * /merge-pdf never downloads the range parser, and a visit to /split-pdf never downloads
 * the zip writer.
 */
function lazyWorkspace<P>(load: () => Promise<{ default: ComponentType<P> }>) {
  return dynamic(load, { ssr: false, loading: () => <WorkspaceFallback /> });
}

/** The tools that still run on the placeholder, until their own phase lands. */
const PlaceholderWorkspace = lazyWorkspace<{ toolId: ToolId }>(() => import("./tool-workspace"));

const WORKSPACES: Partial<Record<ToolId, ComponentType>> = {
  merge: lazyWorkspace(() => import("@/components/tools/merge/merge-workspace")),
  organize: lazyWorkspace(() => import("@/components/tools/organize/organize-workspace")),
  "page-numbers": lazyWorkspace(
    () => import("@/components/tools/page-numbers/page-numbers-workspace"),
  ),
  "pdf-to-jpg": lazyWorkspace(() => import("@/components/tools/pdf-to-jpg/pdf-to-jpg-workspace")),
  rotate: lazyWorkspace(() => import("@/components/tools/rotate/rotate-workspace")),
  split: lazyWorkspace(() => import("@/components/tools/split/split-workspace")),
};

function WorkspaceFallback() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="h-72 w-full max-w-xl animate-pulse rounded-xl bg-muted" aria-hidden />
      <span className="sr-only">Loading the workspace</span>
    </div>
  );
}

export function ToolPage({ toolId }: { toolId: ToolId }) {
  const Workspace = WORKSPACES[toolId];
  return Workspace ? <Workspace /> : <PlaceholderWorkspace toolId={toolId} />;
}
