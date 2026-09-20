import { formatCount, formatPercent } from "@/components/admin/format";
import type { RuntimeSplitRow } from "@/lib/stats/queries";
import type { ToolRuntime } from "@/lib/tools";

const LABELS: Record<ToolRuntime, string> = {
  browser: "Browser (never uploaded)",
  backend: "Backend (server-side)",
  hybrid: "Hybrid",
};

const FILL_CLASS: Record<ToolRuntime, string> = {
  browser: "bg-teal-500 dark:bg-teal-400",
  backend: "bg-rose-500 dark:bg-rose-400",
  hybrid: "bg-amber-500 dark:bg-amber-400",
};

interface RuntimeSplitProps {
  rows: RuntimeSplitRow[];
}

/** The privacy claim, quantified: how much of what actually happens here never left the
 *  visitor's browser. */
export function RuntimeSplit({ rows }: RuntimeSplitProps) {
  const total = rows.reduce((sum, row) => sum + row.runs, 0);

  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted">
        {rows.map((row) => (
          <div
            key={row.runsIn}
            className={FILL_CLASS[row.runsIn]}
            style={{ width: `${total > 0 ? (row.runs / total) * 100 : 0}%` }}
            title={`${LABELS[row.runsIn]}: ${formatCount(row.runs)} runs`}
          />
        ))}
      </div>
      <ul className="space-y-1.5 text-sm">
        {rows.map((row) => (
          <li key={row.runsIn} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <span className={`size-2 shrink-0 rounded-full ${FILL_CLASS[row.runsIn]}`} />
              {LABELS[row.runsIn]}
            </span>
            <span className="tabular-nums text-muted-foreground">
              {formatCount(row.runs)} runs · {formatPercent(row.runs, total)}
            </span>
          </li>
        ))}
        {rows.length === 0 && <li className="text-muted-foreground">No runs yet.</li>}
      </ul>
    </div>
  );
}
