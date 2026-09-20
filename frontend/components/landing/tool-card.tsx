import { Laptop, Server } from "lucide-react";
import Link from "next/link";

import { ACCENT_TILE_CLASS, type Tool, type ToolRuntime, toolHref } from "@/lib/tools";
import { cn } from "@/lib/utils";

const RUNTIME_LABEL: Record<ToolRuntime, string> = {
  browser: "Runs in your browser",
  backend: "Runs on the server",
  hybrid: "Runs in your browser or on the server",
};

function RuntimeIndicator({ runsIn }: { runsIn: ToolRuntime }) {
  return (
    <span
      className="mt-auto flex items-center gap-1 pt-2 text-muted-foreground/80"
      title={RUNTIME_LABEL[runsIn]}
    >
      {runsIn !== "backend" && <Laptop className="size-3.5" aria-hidden />}
      {runsIn === "hybrid" && <span className="text-[10px] leading-none">/</span>}
      {runsIn !== "browser" && <Server className="size-3.5" aria-hidden />}
      <span className="sr-only">{RUNTIME_LABEL[runsIn]}</span>
    </span>
  );
}

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

      <RuntimeIndicator runsIn={tool.runsIn} />
    </Link>
  );
}
