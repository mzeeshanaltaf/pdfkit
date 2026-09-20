import { formatCount, formatPercent } from "@/components/admin/format";
import type { ToolBreakdownRow } from "@/lib/stats/queries";
import { getTool, type ToolAccent } from "@/lib/tools";

const BAR_FILL_CLASS: Record<ToolAccent, string> = {
  teal: "bg-teal-500 dark:bg-teal-400",
  indigo: "bg-indigo-500 dark:bg-indigo-400",
  amber: "bg-amber-500 dark:bg-amber-400",
  rose: "bg-rose-500 dark:bg-rose-400",
};

interface ToolBarListProps {
  rows: ToolBreakdownRow[];
  totalRuns: number;
}

/** Ranked horizontal bars — the "which tool is used most" answer. Rows with zero runs
 *  still render (`toolBreakdownWithZeros`), at zero width, so the list is always all 12. */
export function ToolBarList({ rows, totalRuns }: ToolBarListProps) {
  const maxRuns = Math.max(1, ...rows.map((row) => row.runs));

  return (
    <div className="space-y-3">
      {rows.map((row) => {
        const tool = getTool(row.tool);
        const widthPercent = Math.round((row.runs / maxRuns) * 100);
        return (
          <div key={row.tool} className="grid grid-cols-[minmax(0,1fr)] gap-1.5 sm:grid-cols-[9rem_1fr] sm:items-center sm:gap-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <tool.icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">{tool.name}</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full ${BAR_FILL_CLASS[tool.accent]}`}
                  style={{ width: `${widthPercent}%` }}
                />
              </div>
              <div className="w-40 shrink-0 text-xs text-muted-foreground tabular-nums">
                {formatCount(row.runs)} runs · {formatCount(row.files)} files ·{" "}
                {formatPercent(row.runs, totalRuns)} share ·{" "}
                {row.runs > 0 ? formatPercent(row.doneRuns, row.runs) : "—"} ok
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
