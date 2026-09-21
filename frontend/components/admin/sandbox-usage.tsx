import { formatCount, formatUsd } from "@/components/admin/format";
import type { SandboxOperationRow } from "@/lib/stats/queries";

const OPERATION_LABELS: Record<string, string> = {
  ocr: "OCR",
  word: "PDF to Word",
  markdown: "PDF to Markdown",
  compress: "Compress",
};

const BAR_FILL_CLASS = "bg-indigo-500 dark:bg-indigo-400";

interface SandboxUsageProps {
  rows: SandboxOperationRow[];
}

/** Ranked horizontal bars, same idiom as `ToolBarList` — which operation the sandboxes are
 *  actually spent on, and roughly what each one costs. */
export function SandboxUsage({ rows }: SandboxUsageProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No offloaded runs yet.</p>;
  }

  const maxSandboxes = Math.max(1, ...rows.map((row) => row.sandboxes));

  return (
    <div className="space-y-3">
      {rows.map((row) => {
        const widthPercent = Math.round((row.sandboxes / maxSandboxes) * 100);
        return (
          <div
            key={row.operation}
            className="grid grid-cols-[minmax(0,1fr)] gap-1.5 sm:grid-cols-[9rem_1fr] sm:items-center sm:gap-3"
          >
            <div className="text-sm font-medium">
              {OPERATION_LABELS[row.operation] ?? row.operation}
            </div>
            <div className="flex items-center gap-3">
              <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                <div className={`h-full rounded-full ${BAR_FILL_CLASS}`} style={{ width: `${widthPercent}%` }} />
              </div>
              <div className="w-48 shrink-0 text-xs text-muted-foreground tabular-nums">
                {formatCount(row.sandboxes)} sandboxes · {formatUsd(row.estimatedCostUsd)} est.
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
