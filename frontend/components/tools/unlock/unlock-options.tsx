"use client";

import { KeyRound, Lock, LockOpen } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { formatBytes } from "@/lib/format";

export function UnlockOptions() {
  const { files } = useToolShell();
  const locked = files.filter((file) => file.error?.kind === "encrypted");
  const broken = files.filter((file) => file.error && file.error.kind !== "encrypted");

  return (
    <div className="space-y-6">
      <div className="flex gap-2.5 rounded-lg border border-border bg-muted/50 p-3.5 text-sm leading-relaxed">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <p>
          Just press the unlock button. If a file needs a password to open, you will be asked
          for it one file at a time.
        </p>
      </div>

      {files.length > 0 && (
        <section>
          <h2 className="text-sm font-medium">Files</h2>
          <ul className="mt-3 space-y-2">
            {files.map((file) => {
              const isLocked = file.error?.kind === "encrypted";
              const isBroken = Boolean(file.error) && !isLocked;
              const Icon = isLocked ? Lock : LockOpen;

              return (
                <li
                  key={file.id}
                  className="flex items-center gap-2.5 rounded-lg border border-border p-2.5 text-sm"
                >
                  <Icon
                    className={
                      isLocked
                        ? "size-4 shrink-0 text-amber-600 dark:text-amber-400"
                        : "size-4 shrink-0 text-muted-foreground"
                    }
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={file.name}>
                      {file.name}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {isBroken
                        ? file.error?.message
                        : isLocked
                          ? `${formatBytes(file.size)} · needs a password`
                          : `${formatBytes(file.size)} · opens without one`}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {broken.length === 0 && locked.length === 0 && files.length > 0 && (
        <p className="border-t border-border pt-5 text-sm text-muted-foreground">
          None of these files ask for a password to open. Unlocking still strips any owner
          restrictions on printing, copying and editing.
        </p>
      )}
    </div>
  );
}
