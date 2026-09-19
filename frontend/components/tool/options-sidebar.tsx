"use client";

import { ArrowRight, Info } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface OptionsSidebarProps {
  title: string;
  /** Short explanatory note at the top of the panel. */
  info?: ReactNode;
  children?: ReactNode;
  ctaLabel: string;
  ctaDisabled?: boolean;
  onSubmit: () => void;
}

/**
 * The right-hand column of every tool: title, options, and a CTA pinned to the bottom.
 * Below `lg` it stacks under the canvas and the CTA scrolls with the page.
 */
export function OptionsSidebar({
  title,
  info,
  children,
  ctaLabel,
  ctaDisabled = false,
  onSubmit,
}: OptionsSidebarProps) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-t border-border bg-background lg:h-[calc(100dvh-4rem)] lg:w-[380px] lg:border-t-0 lg:border-l xl:w-[420px]">
      {/* An `h2`, matching the dropzone: the route's `h1` is server-rendered in
          `ToolSeoSection`, because this whole tree is `ssr: false`. */}
      <h2 className="border-b border-border px-6 py-5 text-center text-2xl font-semibold tracking-tight">
        {title}
      </h2>

      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6">
        {info && (
          <div className="flex gap-2.5 rounded-lg bg-brand/8 p-3.5 text-sm leading-relaxed text-foreground/85">
            <Info className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
            <div>{info}</div>
          </div>
        )}
        {children}
      </div>

      {/*
        On a phone the sidebar is just the bottom of a long page, so the CTA would sit below
        every option and need a scroll to reach. Sticking it to the viewport keeps it in
        reach the whole way down; from `lg` the sidebar is its own column and it is already
        pinned by the flex layout.
      */}
      <div className="sticky bottom-0 border-t border-border bg-background p-4 lg:static">
        <Button
          size="lg"
          className="h-14 w-full gap-2 text-base font-semibold"
          disabled={ctaDisabled}
          onClick={onSubmit}
        >
          {ctaLabel}
          <ArrowRight className="size-5" data-icon="inline-end" aria-hidden />
        </Button>
      </div>
    </aside>
  );
}
