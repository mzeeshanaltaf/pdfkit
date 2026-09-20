import { formatCount } from "@/components/admin/format";
import type { RunsPerDayRow } from "@/lib/stats/queries";

interface DayChartProps {
  rows: RunsPerDayRow[];
}

/** Plain CSS columns — no charting dependency, per the phase doc. Its own horizontal-scroll
 *  container keeps 30 bars legible at phone width without the page itself scrolling. */
export function DayChart({ rows }: DayChartProps) {
  const max = Math.max(1, ...rows.map((row) => row.runs));

  return (
    <div className="overflow-x-auto">
      <div className="flex h-32 min-w-[480px] items-end gap-1.5">
        {rows.map((row) => {
          const heightPercent = Math.max(2, Math.round((row.runs / max) * 100));
          const date = new Date(`${row.day}T00:00:00Z`);
          const label = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
          return (
            <div key={row.day} className="flex flex-1 flex-col items-center gap-1">
              <div
                title={`${label}: ${formatCount(row.runs)} runs`}
                className="w-full rounded-t-sm bg-brand/70 transition-[height] hover:bg-brand"
                style={{ height: `${heightPercent}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex min-w-[480px] justify-between text-[10px] text-muted-foreground">
        <span>{rows[0] && new Date(`${rows[0].day}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
        <span>Today</span>
      </div>
    </div>
  );
}
