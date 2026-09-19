import Link from "next/link";

import { MAX_UPLOAD_LABEL } from "@/lib/constants";
import { TOOL_SEO } from "@/lib/seo/tool-content";
import { ACCENT_TILE_CLASS, TOOLS, getTool, toolHref, type ToolId } from "@/lib/tools";
import { cn } from "@/lib/utils";

const RUNS_IN_NOTE = {
  browser: "Runs in your browser. Nothing is uploaded.",
  backend: `Runs on the server. Files up to ${MAX_UPLOAD_LABEL} are processed and deleted in the same request.`,
  hybrid: "Runs in your browser, or on the server for embedded images.",
} as const;

/**
 * The crawlable half of a tool page, rendered on the server below the workspace.
 *
 * The workspace above it is `ssr: false` and cannot be anything else, so this section
 * carries the page's only server-rendered `h1` and its only complete set of internal
 * links — the header's "All tools" menu is a Radix dropdown whose items do not exist in
 * the HTML until it is opened, and tool routes have no footer of their own.
 */
export function ToolSeoSection({ toolId }: { toolId: ToolId }) {
  const tool = getTool(toolId);
  const { h1, howTo, intro, steps, faqs } = TOOL_SEO[toolId];
  const others = TOOLS.filter((candidate) => candidate.id !== toolId);

  return (
    <section className="border-t border-border bg-muted/40">
      <div className="mx-auto w-full max-w-[1400px] px-4 py-16 sm:px-6 lg:py-20">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-16">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
              {h1}
            </h1>
            {intro.map((paragraph) => (
              <p
                key={paragraph}
                className="mt-4 max-w-[62ch] text-base leading-relaxed text-muted-foreground"
              >
                {paragraph}
              </p>
            ))}

            <p className="mt-6 inline-flex rounded-full bg-brand/10 px-3.5 py-1.5 text-xs font-medium text-brand">
              {RUNS_IN_NOTE[tool.runsIn]}
            </p>

            <h2 className="mt-12 text-xl font-semibold tracking-tight">{howTo}</h2>
            <ol className="mt-5 grid gap-5 sm:grid-cols-3 lg:gap-6">
              {steps.map((step, index) => (
                <li key={step.title}>
                  <span
                    className={cn(
                      "flex size-7 items-center justify-center rounded-md text-sm font-semibold",
                      ACCENT_TILE_CLASS[tool.accent],
                    )}
                    aria-hidden
                  >
                    {index + 1}
                  </span>
                  <h3 className="mt-3 font-medium tracking-tight">{step.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>
          </div>

          <div>
            <h2 className="text-xl font-semibold tracking-tight">Questions</h2>
            <dl className="mt-5 divide-y divide-border border-y border-border">
              {faqs.map(({ q, a }) => (
                <div key={q} className="py-4">
                  <dt className="text-sm font-medium tracking-tight">{q}</dt>
                  <dd className="mt-1.5 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
                    {a}
                  </dd>
                </div>
              ))}
            </dl>

            <h2 className="mt-10 text-xl font-semibold tracking-tight">Other PDF tools</h2>
            <nav aria-label="Other PDF tools" className="mt-4 flex flex-wrap gap-2">
              {others.map((other) => (
                <Link
                  key={other.id}
                  href={toolHref(other)}
                  className="rounded-full border border-border bg-background px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-brand/40 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  {other.name}
                </Link>
              ))}
            </nav>
          </div>
        </div>
      </div>
    </section>
  );
}
