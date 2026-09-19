import type { ToolFile } from "@/components/tool/types";
import {
  PageNumberError,
  planPageNumbers,
  type FontFamily,
  type MarginSize,
  type NumberingMode,
  type NumberingPlan,
  type NumberPosition,
  type PageNumberOptions,
} from "@/lib/pdf/pageNumbers";

export type TemplateId = "plain" | "page" | "pageOf" | "custom";

export interface TemplatePreset {
  id: TemplateId;
  /** What the option looks like once it is stamped, which is the only useful label. */
  label: string;
  template: string;
}

export const TEMPLATE_PRESETS: TemplatePreset[] = [
  { id: "plain", label: "1", template: "{n}" },
  { id: "page", label: "Page 1", template: "Page {n}" },
  { id: "pageOf", label: "Page 1 of 10", template: "Page {n} of {N}" },
  { id: "custom", label: "Custom text", template: "" },
];

export const FONT_LABELS: Record<FontFamily, string> = {
  helvetica: "Helvetica",
  times: "Times",
  courier: "Courier",
};

export const MARGIN_LABELS: Record<MarginSize, string> = {
  small: "Small",
  recommended: "Recommended",
  big: "Big",
};

export const TEXT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24] as const;

/**
 * The panel's own state. The numeric fields are kept as strings so a field can be empty
 * while the user retypes it, instead of snapping back to a default under their cursor.
 */
export interface PageNumbersState {
  mode: NumberingMode;
  position: NumberPosition;
  margin: MarginSize;
  firstNumber: string;
  fromPage: string;
  toPage: string;
  templateId: TemplateId;
  customTemplate: string;
  font: FontFamily;
  size: number;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  color: string;
  /** Which loaded file the preview is showing; null means "the first readable one". */
  previewFileId: string | null;
}

export function createPageNumbersState(): PageNumbersState {
  return {
    mode: "single",
    position: { vertical: "bottom", horizontal: "center" },
    margin: "recommended",
    firstNumber: "1",
    fromPage: "",
    toPage: "",
    templateId: "plain",
    customTemplate: "",
    font: "helvetica",
    size: 12,
    bold: false,
    italic: false,
    underline: false,
    color: "#222222",
    previewFileId: null,
  };
}

/**
 * The file the preview is showing, and therefore the one the page range is validated
 * against. Falls back to the first readable file, which covers both the single-file case and
 * the moment just after the chosen file is removed from the workspace.
 */
export function previewFile(
  files: ToolFile[],
  previewFileId: string | null,
): ToolFile | undefined {
  const readable = files.filter((file) => !file.error);
  return readable.find((file) => file.id === previewFileId) ?? readable[0];
}

export function templateFor(state: PageNumbersState): string {
  if (state.templateId === "custom") return state.customTemplate;
  return TEMPLATE_PRESETS.find((preset) => preset.id === state.templateId)!.template;
}

/**
 * An empty bound means "the natural end of the document", which is what the placeholder on
 * each input says. That keeps the defaults valid before the user has typed anything.
 */
function toBound(value: string, fallback: number): number {
  const trimmed = value.trim();
  return trimmed === "" ? fallback : Number(trimmed);
}

/** Flattens the panel's state into the shape `lib/pdf/pageNumbers` works from. */
export function toPageNumberOptions(
  state: PageNumbersState,
  pageCount: number,
): PageNumberOptions {
  return {
    mode: state.mode,
    position: state.position,
    margin: state.margin,
    firstNumber: toBound(state.firstNumber, 1),
    fromPage: toBound(state.fromPage, 1),
    toPage: toBound(state.toPage, pageCount),
    template: templateFor(state),
    font: state.font,
    size: state.size,
    bold: state.bold,
    italic: state.italic,
    underline: state.underline,
    color: state.color,
  };
}

export interface PageNumbersPlan {
  plan: NumberingPlan | null;
  /** A message ready to show the user, or null when the options are usable. */
  issue: string | null;
}

/**
 * Validates and plans in one pass, so the sidebar's error message, the CTA gate and the
 * thumbnail preview can never disagree about what the current options mean.
 */
export function planFromState(
  state: PageNumbersState,
  pageCount: number | null,
): PageNumbersPlan {
  // Nothing to validate against until the file has been read.
  if (pageCount === null) return { plan: null, issue: null };

  try {
    return {
      plan: planPageNumbers(toPageNumberOptions(state, pageCount), pageCount),
      issue: null,
    };
  } catch (error) {
    return {
      plan: null,
      issue:
        error instanceof PageNumberError ? error.message : "These options cannot be used.",
    };
  }
}
