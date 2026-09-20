import type { ToolId } from "@/lib/tools";

export interface RunEvent {
  tool: ToolId;
  outcome: "done" | "error" | "cancelled";
  fileCount: number;
  /** Null when the file list was still loading page counts at the time of the event. */
  pageCount: number | null;
  bytesIn: number;
  bytesOut: number;
  durationMs: number;
  errorCode?: string | null;
}

/**
 * Fire-and-forget: no await, no state, no error surface. A dropped stat must never matter
 * to the tool run it describes. `keepalive` matters because a "done" event often coincides
 * with the user clicking Download and immediately leaving the page.
 */
export function recordRun(event: RunEvent): void {
  fetch("/api/stats/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    keepalive: true,
    body: JSON.stringify(event),
  }).catch(() => {});
}
