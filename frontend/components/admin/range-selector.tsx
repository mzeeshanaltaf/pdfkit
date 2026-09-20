import Link from "next/link";

import { STATS_RANGES, type StatsRange } from "@/lib/stats/queries";
import { cn } from "@/lib/utils";

interface RangeSelectorProps {
  current: StatsRange;
}

/** A plain link group, not client state — the page is a server component reading
 *  `searchParams`, so changing the range is just a navigation. */
export function RangeSelector({ current }: RangeSelectorProps) {
  return (
    <div className="inline-flex rounded-lg border border-border bg-card p-0.5">
      {STATS_RANGES.map(({ value, label }) => (
        <Link
          key={value}
          href={`/admin?range=${value}`}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
            value === current
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </Link>
      ))}
    </div>
  );
}
