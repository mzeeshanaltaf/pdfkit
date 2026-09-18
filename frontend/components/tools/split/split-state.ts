import { planSplit, SplitError, type SplitChunk, type SplitInput } from "@/lib/pdf/split";

export type SplitTab = "range" | "pages";
export type RangeMode = "custom" | "fixed";
export type PagesMode = "all" | "select";

/**
 * One row of the custom-range editor. The bounds are kept as strings, not numbers, so the
 * field can be empty while the user retypes it without the value snapping back to a
 * default under their cursor.
 */
export interface RangeRow {
  id: string;
  from: string;
  to: string;
}

export interface SplitState {
  tab: SplitTab;
  rangeMode: RangeMode;
  ranges: RangeRow[];
  every: string;
  pagesMode: PagesMode;
  pages: string;
  mergeOutput: boolean;
}

export function newRangeRow(from = "", to = ""): RangeRow {
  return { id: crypto.randomUUID(), from, to };
}

export function createSplitState(): SplitState {
  return {
    tab: "range",
    rangeMode: "custom",
    ranges: [newRangeRow()],
    every: "2",
    pagesMode: "all",
    pages: "",
    mergeOutput: false,
  };
}

/**
 * An empty bound means "the natural end of the document", which is what the placeholder on
 * each input says. That keeps a fresh range valid before the user has typed anything,
 * instead of greeting them with a validation error.
 */
function toBound(value: string, fallback: number): number {
  const trimmed = value.trim();
  return trimmed === "" ? fallback : Number(trimmed);
}

/** Flattens the panel's state into the shape `lib/pdf/split` works from. */
export function toSplitInput(state: SplitState, pageCount: number): SplitInput {
  const base = { ranges: [], every: 0, pages: "", mergeOutput: state.mergeOutput };

  if (state.tab === "pages") {
    return {
      ...base,
      mode: "pages",
      // "Extract all" is just every page named explicitly, so one code path covers both.
      pages: state.pagesMode === "all" ? `1-${pageCount}` : state.pages,
    };
  }

  if (state.rangeMode === "fixed") {
    return { ...base, mode: "fixed", every: toBound(state.every, Number.NaN) };
  }

  return {
    ...base,
    mode: "ranges",
    ranges: state.ranges.map((row) => ({
      from: toBound(row.from, 1),
      to: toBound(row.to, pageCount),
    })),
  };
}

export interface SplitPlan {
  chunks: SplitChunk[] | null;
  /** A message ready to show the user, or null when the options are usable. */
  issue: string | null;
}

/**
 * Validates and plans in one pass, so the sidebar's error message and the canvas preview can
 * never disagree about what the current options mean.
 */
export function planFromState(state: SplitState, pageCount: number | null): SplitPlan {
  // Nothing to validate against until the file has been read.
  if (pageCount === null) return { chunks: null, issue: null };

  try {
    return { chunks: planSplit(toSplitInput(state, pageCount), pageCount), issue: null };
  } catch (error) {
    return {
      chunks: null,
      issue: error instanceof SplitError ? error.message : "These options cannot be used.",
    };
  }
}
