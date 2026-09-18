import { Lock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { getTool, toolHref } from "@/lib/tools";

/**
 * Shown when a browser-side tool cannot open a file because it is encrypted. pdf-lib and
 * pdf.js both raise a password error long before anything can be edited, so the only useful
 * next step is the Unlock tool.
 */
export function EncryptedNotice({ filenames }: { filenames: string[] }) {
  const unlock = getTool("unlock");
  const one = filenames.length === 1;

  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
      <Lock className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {one ? "This PDF is password protected" : "Some of these PDFs are password protected"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {one ? filenames[0] : filenames.join(", ")} cannot be read until the password is
          removed. Unlock {one ? "it" : "them"} first, then come back.
        </p>
        <Button asChild variant="outline" size="sm" className="mt-3 bg-background">
          <Link href={toolHref(unlock)}>Go to {unlock.name}</Link>
        </Button>
      </div>
    </div>
  );
}
