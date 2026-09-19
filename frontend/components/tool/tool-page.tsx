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

const WORKSPACES: Record<ToolId, ComponentType> = {
  compress: lazyWorkspace(() => import("@/components/tools/compress/compress-workspace")),
  merge: lazyWorkspace(() => import("@/components/tools/merge/merge-workspace")),
  ocr: lazyWorkspace(() => import("@/components/tools/ocr/ocr-workspace")),
  organize: lazyWorkspace(() => import("@/components/tools/organize/organize-workspace")),
  "page-numbers": lazyWorkspace(
    () => import("@/components/tools/page-numbers/page-numbers-workspace"),
  ),
  "pdf-to-jpg": lazyWorkspace(() => import("@/components/tools/pdf-to-jpg/pdf-to-jpg-workspace")),
  protect: lazyWorkspace(() => import("@/components/tools/protect/protect-workspace")),
  rotate: lazyWorkspace(() => import("@/components/tools/rotate/rotate-workspace")),
  split: lazyWorkspace(() => import("@/components/tools/split/split-workspace")),
  unlock: lazyWorkspace(() => import("@/components/tools/unlock/unlock-workspace")),
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

  // The workspace used to be the only thing on the route, so `flex-1` was enough to make it
  // fill the viewport. It now has the server-rendered `ToolSeoSection` as a sibling, and a
  // flex child will happily shrink to share the space — hence the explicit floor of one
  // viewport minus the 4rem header. The content below stays below the fold, where it was
  // designed to be, and the options sidebar still runs full height.
  return (
    <div className="flex min-h-[calc(100svh-4rem)] flex-col">
      <Workspace />
    </div>
  );
}
