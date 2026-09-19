"use client";

import { Lock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { handOffFiles } from "@/lib/file-handoff";
import { getTool, toolHref } from "@/lib/tools";

import type { ToolFile } from "./types";

/**
 * Shown when a browser-side tool cannot open a file because it is encrypted. pdf-lib and
 * pdf.js both raise a password error long before anything can be edited, so the only useful
 * next step is the Unlock tool — and the button hands the file over, so it is already loaded
 * on arrival instead of having to be found again.
 */
export function EncryptedNotice({ files }: { files: ToolFile[] }) {
  const unlock = getTool("unlock");
  const one = files.length === 1;
  const names = files.map((file) => file.name);

  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
      <Lock className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {one ? "This PDF is password protected" : "Some of these PDFs are password protected"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {one ? names[0] : names.join(", ")} cannot be read until the password is removed.
          Unlock {one ? "it" : "them"} first, then come back.
        </p>
        <Button asChild variant="outline" size="sm" className="mt-3 bg-background">
          <Link
            href={toolHref(unlock)}
            onClick={() => handOffFiles(files.map((file) => file.file))}
          >
            Unlock {one ? "this file" : "these files"}
          </Link>
        </Button>
      </div>
    </div>
  );
}
