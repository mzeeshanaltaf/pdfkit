import Link from "next/link";

import { ACCENT_TILE_CLASS, type Tool, toolHref } from "@/lib/tools";
import { cn } from "@/lib/utils";

export function ToolCard({ tool }: { tool: Tool }) {
  const Icon = tool.icon;

  return (
    <Link
      href={toolHref(tool)}
      className="group flex flex-col gap-3 rounded-xl border border-border bg-card p-5 transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-[0_10px_30px_-18px_var(--brand)] focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <span
        className={cn(
          "flex size-10 items-center justify-center rounded-lg",
          ACCENT_TILE_CLASS[tool.accent],
        )}
      >
        <Icon className="size-5" aria-hidden />
      </span>

      <span className="font-semibold tracking-tight text-card-foreground">{tool.name}</span>
      <span className="text-sm leading-relaxed text-muted-foreground">{tool.tagline}</span>

      <span className="mt-auto pt-2 text-xs font-medium text-muted-foreground/80">
        {tool.runsIn === "browser"
          ? "Runs in your browser"
          : tool.runsIn === "hybrid"
            ? "Browser or server"
            : "Runs on the server"}
      </span>
    </Link>
  );
}
