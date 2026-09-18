import Link from "next/link";

import { APP_NAME } from "@/lib/constants";
import { cn } from "@/lib/utils";

/**
 * The wordmark. A two-tone name rather than a drawn logo, so there is exactly one place to
 * change if the product is renamed.
 */
export function Brand({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      aria-label={`${APP_NAME} home`}
      className={cn(
        "inline-flex items-baseline gap-px rounded-lg text-lg font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        className,
      )}
    >
      <span className="text-brand">PDF</span>
      <span className="text-foreground">{APP_NAME.replace("PDF", "")}</span>
    </Link>
  );
}
