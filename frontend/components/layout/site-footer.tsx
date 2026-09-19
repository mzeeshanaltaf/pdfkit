import Link from "next/link";

import { Brand } from "@/components/layout/brand";
import { APP_NAME } from "@/lib/constants";
import { TOOLS, toolHref } from "@/lib/tools";

const SECONDARY_LINKS = [
  { href: "/contact", label: "Contact" },
  { href: "/privacy", label: "Privacy policy" },
] as const;

const LINK_CLASS =
  "rounded-lg text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none";

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

          <div className="flex flex-col gap-8 sm:flex-row sm:gap-10 lg:gap-16">
            <nav
              aria-label="All tools"
              className="grid grid-cols-2 gap-x-10 gap-y-2 sm:grid-cols-3"
            >
              {TOOLS.map((tool) => (
                <Link key={tool.id} href={toolHref(tool)} className={LINK_CLASS}>
                  {tool.name}
                </Link>
              ))}
            </nav>

            <nav aria-label="More" className="flex flex-col gap-2">
              {SECONDARY_LINKS.map(({ href, label }) => (
                <Link key={href} href={href} className={LINK_CLASS}>
                  {label}
                </Link>
              ))}
            </nav>
          </div>
        </div>

        <div className="mt-8 flex flex-col gap-2 border-t border-border pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>{APP_NAME}. Self-hosted PDF tools.</p>
          <p>
            Developed with <span aria-label="love">💖</span> by{" "}
            <a
              href="https://zeeshanai.cloud"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-sm font-medium text-foreground underline underline-offset-4 transition-colors hover:text-brand focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              Zeeshan Altaf
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
