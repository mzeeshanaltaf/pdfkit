import { formatCount, formatPercent } from "@/components/admin/format";
import type { Placement, PlacementSplitRow } from "@/lib/stats/queries";

const LABELS: Record<Placement, string> = {
  server: "On the VPS",
  sandbox: "In a Daytona sandbox",
};

const FILL_CLASS: Record<Placement, string> = {
  server: "bg-sky-500 dark:bg-sky-400",
  sandbox: "bg-violet-500 dark:bg-violet-400",
};

interface PlacementSplitProps {
  rows: PlacementSplitRow[];
}

/** Of the work that reaches the server, how much left the VPS for a Daytona sandbox. */
export function PlacementSplit({ rows }: PlacementSplitProps) {
  const total = rows.reduce((sum, row) => sum + row.runs, 0);

  return (
    <div className="space-y-3">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted">
        {rows.map((row) => (
          <div
            key={row.placement}
            className={FILL_CLASS[row.placement]}
            style={{ width: `${total > 0 ? (row.runs / total) * 100 : 0}%` }}
            title={`${LABELS[row.placement]}: ${formatCount(row.runs)} runs`}
          />
        ))}
      </div>
      <ul className="space-y-1.5 text-sm">
        {rows.map((row) => (
          <li key={row.placement} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <span className={`size-2 shrink-0 rounded-full ${FILL_CLASS[row.placement]}`} />
              {LABELS[row.placement]}
            </span>
            <span className="tabular-nums text-muted-foreground">
              {formatCount(row.runs)} runs · {formatPercent(row.runs, total)}
            </span>
          </li>
        ))}
        {rows.length === 0 && (
          <li className="text-muted-foreground">
            No backend runs have a recorded placement yet.
          </li>
        )}
      </ul>
    </div>
  );
}
