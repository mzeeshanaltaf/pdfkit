import { cn } from "@/lib/utils";

/**
 * Colours for the source-file chips, written out in full so Tailwind can see the classes.
 * They are assigned by position in the file list, not by tool accent: their only job is to
 * tell two documents apart in a combined page grid.
 */
const CHIP_CLASSES = [
  "border-teal-500/40 bg-teal-500/12 text-teal-700 dark:text-teal-300",
  "border-violet-500/40 bg-violet-500/12 text-violet-700 dark:text-violet-300",
  "border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300",
  "border-rose-500/40 bg-rose-500/12 text-rose-700 dark:text-rose-300",
  "border-sky-500/40 bg-sky-500/12 text-sky-700 dark:text-sky-300",
  "border-lime-600/40 bg-lime-600/12 text-lime-700 dark:text-lime-300",
] as const;

/** A, B, C … then A2, B2 once the alphabet runs out. */
export function sourceLetter(index: number): string {
  const letter = String.fromCharCode(65 + (index % 26));
  const cycle = Math.floor(index / 26);
  return cycle === 0 ? letter : `${letter}${cycle + 1}`;
}

export function sourceChipClass(index: number): string {
  return CHIP_CLASSES[index % CHIP_CLASSES.length];
}

interface SourceChipProps {
  /** Position of the file in the workspace list, which is what picks letter and colour. */
  index: number;
  /** Shown as the chip's tooltip, normally the filename. */
  title?: string;
  className?: string;
}

/** The letter-and-colour tag that says which document a page came from. */
export function SourceChip({ index, title, className }: SourceChipProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex min-w-5 items-center justify-center rounded-md border px-1.5 text-[10px] font-semibold",
        sourceChipClass(index),
        className,
      )}
    >
      {sourceLetter(index)}
    </span>
  );
}
