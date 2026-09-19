"use client";

import { ChevronDown, Mail } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Brand } from "@/components/layout/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ACCENT_TILE_CLASS, TOOLS, toolHref } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** Two shortcuts plus the full list, so the bar stays on one line at every width. */
const QUICK_LINKS = ["merge", "compress", "split"] as const;

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 h-16 shrink-0 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-full max-w-[1400px] items-center gap-2 px-4 sm:px-6">
        <Brand />

        <nav className="ml-4 hidden items-center gap-1 sm:flex">
          {QUICK_LINKS.map((id) => {
            const tool = TOOLS.find((candidate) => candidate.id === id)!;
            const href = toolHref(tool);
            return (
              <Button
                key={tool.id}
                asChild
                variant="ghost"
                size="sm"
                className={cn(pathname === href && "bg-muted text-foreground")}
              >
                <Link href={href}>{tool.name}</Link>
              </Button>
            );
          })}
        </nav>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="ml-auto sm:ml-1">
              All tools
              <ChevronDown data-icon="inline-end" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            {TOOLS.map((tool) => {
              const Icon = tool.icon;
              return (
                <DropdownMenuItem key={tool.id} asChild>
                  <Link href={toolHref(tool)} className="gap-2.5">
                    <span
                      className={cn(
                        "flex size-6 items-center justify-center rounded-md",
                        ACCENT_TILE_CLASS[tool.accent],
                      )}
                    >
                      <Icon className="size-3.5" aria-hidden />
                    </span>
                    {tool.name}
                  </Link>
                </DropdownMenuItem>
              );
            })}

            {/* The header's Contact link is hidden below `sm`, so the menu carries it too. */}
            <DropdownMenuSeparator className="sm:hidden" />
            <DropdownMenuItem asChild className="sm:hidden">
              <Link href="/contact" className="gap-2.5">
                <span className="flex size-6 items-center justify-center rounded-md bg-muted">
                  <Mail className="size-3.5" aria-hidden />
                </span>
                Contact
              </Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          asChild
          variant="ghost"
          size="sm"
          className={cn("hidden sm:inline-flex", pathname === "/contact" && "bg-muted text-foreground")}
        >
          <Link href="/contact">Contact</Link>
        </Button>

        <div className="ml-auto sm:ml-2">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
