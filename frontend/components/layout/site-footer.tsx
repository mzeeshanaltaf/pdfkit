import Link from "next/link";

import { Brand } from "@/components/layout/brand";
import { APP_NAME } from "@/lib/constants";
import { TOOLS, toolHref } from "@/lib/tools";

export function SiteFooter() {
  return (
    <footer className="shrink-0 border-t border-border bg-background">
      <div className="mx-auto max-w-[1400px] px-4 py-10 sm:px-6">
        <div className="flex flex-col gap-8 lg:flex-row lg:justify-between">
          <div className="max-w-xs">
            <Brand />
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Ten PDF tools, no account and nothing kept. Files sent to the server are deleted
              as soon as the job finishes.
            </p>
          </div>

          <nav aria-label="All tools" className="grid grid-cols-2 gap-x-10 gap-y-2 sm:grid-cols-3">
            {TOOLS.map((tool) => (
              <Link
                key={tool.id}
                href={toolHref(tool)}
                className="rounded-lg text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                {tool.name}
              </Link>
            ))}
          </nav>
        </div>

        <p className="mt-8 border-t border-border pt-6 text-xs text-muted-foreground">
          {APP_NAME}. Self-hosted PDF tools.
        </p>
      </div>
    </footer>
  );
}
