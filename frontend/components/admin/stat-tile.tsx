import type { ReactNode } from "react";

interface StatTileProps {
  label: string;
  value: string;
  sub?: string;
  icon?: ReactNode;
}

export function StatTile({ label, value, sub, icon }: StatTileProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {icon}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}
