"use client";

import { Info, ScanText, Type } from "lucide-react";

import { cn } from "@/lib/utils";

/** Mirrors the backend's `ocr` field on /convert/word and /convert/markdown. */
export type OcrMode = "off" | "auto";

interface OcrModeCardsProps {
  mode: OcrMode;
  onChange: (mode: OcrMode) => void;
  /** How many of the loaded files look like scans, from `useScannedProbe`. */
  scannedCount: number;
  /** What the "off" card promises, which differs between Word and Markdown. */
  offDescription: string;
  onDescription: string;
}

/**
 * The "does this document need reading first" choice.
 *
 * When the loaded files look like scans it says so, but it deliberately does
 * **not** switch the mode: OCR can turn a two-second job into a two-minute one,
 * and choosing that on someone's behalf because a heuristic said so is not a
 * choice they made. The hint explains; the radio still belongs to the user.
 */
export function OcrModeCards({
  mode,
  onChange,
  scannedCount,
  offDescription,
  onDescription,
}: OcrModeCardsProps) {
  return (
    <section>
      <h2 className="text-sm font-medium">Text recognition</h2>

      {scannedCount > 0 && mode === "off" && (
        <div className="mt-3 flex gap-2.5 rounded-lg border border-sky-500/40 bg-sky-500/10 p-3.5 text-sm leading-relaxed">
          <Info
            className="mt-0.5 size-4 shrink-0 text-sky-700 dark:text-sky-300"
            aria-hidden
          />
          <p>
            {scannedCount === 1
              ? "One of these files looks like a scan"
              : `${scannedCount} of these files look like scans`}
            , so there is no text in it to convert. Turn OCR on to read the pages first.
          </p>
        </div>
      )}

      <div className="mt-3 grid gap-3">
        <ModeCard
          icon={Type}
          title="No OCR"
          description={offDescription}
          selected={mode === "off"}
          onSelect={() => onChange("off")}
        />
        <ModeCard
          icon={ScanText}
          title="OCR"
          description={onDescription}
          selected={mode === "auto"}
          onSelect={() => onChange("auto")}
        />
      </div>
    </section>
  );
}

interface ModeCardProps {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  description: string;
  selected: boolean;
  onSelect: () => void;
}

/** The whole box is the hit target — icon, title and blurb, as on PDF to JPG. */
function ModeCard({ icon: Icon, title, description, selected, onSelect }: ModeCardProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-brand/50",
        selected && "border-brand bg-brand/8",
      )}
    >
      <Icon className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden />
      <span className="min-w-0">
        <span className="block text-sm font-medium">{title}</span>
        <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  );
}
