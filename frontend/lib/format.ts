const UNITS = ["B", "KB", "MB", "GB"] as const;

/** Human-readable file size, e.g. 2.4 MB. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1);
  const value = bytes / 1024 ** exponent;
  const digits = value >= 100 || exponent === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[exponent]}`;
}

/** "3 pages" / "1 page" / "" while the page count is still unknown. */
export function formatPageCount(pageCount: number | null): string {
  if (pageCount === null) return "";
  return pageCount === 1 ? "1 page" : `${pageCount} pages`;
}

/** Strips the .pdf extension so tools can build "<name>-merged.pdf" style filenames. */
export function stripExtension(filename: string): string {
  return filename.replace(/\.[a-z0-9]+$/i, "");
}

/** Percentage saved between two sizes, rounded down. Negative values clamp to 0. */
export function percentSmaller(before: number, after: number): number {
  if (before <= 0 || after >= before) return 0;
  return Math.floor(((before - after) / before) * 100);
}
