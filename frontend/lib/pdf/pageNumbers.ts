import { degrees, rgb, StandardFonts, type PDFFont, type PDFPage } from "pdf-lib";

import { loadPdfLibDocument } from "./load";
import { normalizeAngle } from "./rotate";
import { pdfToBlob } from "./save";

export type NumberingMode = "single" | "facing";
export type HorizontalPosition = "left" | "center" | "right";
export type VerticalPosition = "top" | "middle" | "bottom";
export type MarginSize = "small" | "recommended" | "big";
export type FontFamily = "helvetica" | "times" | "courier";

export interface NumberPosition {
  vertical: VerticalPosition;
  horizontal: HorizontalPosition;
}

export interface PageNumberOptions {
  /** `facing` mirrors the horizontal position on even pages, the way a bound book reads. */
  mode: NumberingMode;
  position: NumberPosition;
  margin: MarginSize;
  /** The number printed on the first numbered page. */
  firstNumber: number;
  /** 1-based, inclusive: the stretch of the document that gets numbered. */
  fromPage: number;
  toPage: number;
  /** Text with `{n}` for the page number and `{N}` for the last number. */
  template: string;
  font: FontFamily;
  size: number;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  /** `#rrggbb`. */
  color: string;
}

/** Distance from the paper's edge, in points. */
export const MARGIN_POINTS: Record<MarginSize, number> = {
  small: 16,
  recommended: 32,
  big: 56,
};

export const DEFAULT_TEMPLATE = "{n}";

/** A validation failure with a message that is safe to show the user as-is. */
export class PageNumberError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PageNumberError";
  }
}

/** One stamp the plan will place. */
export interface NumberedPage {
  /** 1-based page in the document. */
  pageNumber: number;
  /** The number printed on it, which is not the page number once `firstNumber` moves. */
  value: number;
  text: string;
  /** Resolved for this page, so facing mode is already folded in. */
  horizontal: HorizontalPosition;
}

export interface NumberingPlan {
  pages: NumberedPage[];
  /** What `{N}` expands to. */
  lastNumber: number;
}

/**
 * Works out what the current options would stamp, without touching the document.
 *
 * The sidebar's error message, the CTA gate and the thumbnail preview all call this, so they
 * cannot disagree about what the options mean. It throws `PageNumberError` rather than
 * returning a half-valid plan.
 */
export function planPageNumbers(options: PageNumberOptions, pageCount: number): NumberingPlan {
  const { fromPage, toPage, firstNumber } = options;

  if (!Number.isInteger(fromPage) || !Number.isInteger(toPage)) {
    throw new PageNumberError("Fill in the first and last page to number.");
  }
  if (fromPage < 1) {
    throw new PageNumberError("Page numbers start at 1.");
  }
  if (fromPage > pageCount || toPage > pageCount) {
    throw new PageNumberError(
      `This PDF has ${pageCount} ${pageCount === 1 ? "page" : "pages"}, so that range does not exist.`,
    );
  }
  if (toPage < fromPage) {
    throw new PageNumberError(`Page ${toPage} comes before page ${fromPage}.`);
  }
  if (!Number.isInteger(firstNumber) || firstNumber < 0) {
    throw new PageNumberError("The first number has to be a whole number, 0 or more.");
  }
  if (!Number.isInteger(options.size) || options.size < 6 || options.size > 48) {
    throw new PageNumberError("Choose a text size between 6 and 48.");
  }
  if (!options.template.includes("{n}")) {
    throw new PageNumberError("The text needs {n} in it, where the number goes.");
  }
  if (!/^#[0-9a-f]{6}$/i.test(options.color)) {
    throw new PageNumberError("The colour has to be a hex value like #222222.");
  }

  // {N} is the last number that will actually be stamped, not the document's page count.
  // With the defaults the two are the same; once the numbering starts partway through, or
  // at a number other than 1, "Page 3 of 6" should still count the numbers, not the paper.
  const lastNumber = firstNumber + (toPage - fromPage);

  const pages: NumberedPage[] = [];
  for (let pageNumber = fromPage; pageNumber <= toPage; pageNumber += 1) {
    const value = firstNumber + (pageNumber - fromPage);
    pages.push({
      pageNumber,
      value,
      text: fillTemplate(options.template, value, lastNumber),
      horizontal: resolveHorizontal(options, pageNumber),
    });
  }

  return { pages, lastNumber };
}

/**
 * In facing mode the number sits on the outside edge of each sheet, which flips on every
 * turn of the page. Parity follows the sheet's position in the document, not the number
 * printed on it: it is the paper that is bound, not the numbering.
 */
function resolveHorizontal(options: PageNumberOptions, pageNumber: number): HorizontalPosition {
  const { horizontal } = options.position;
  if (options.mode !== "facing" || horizontal === "center" || pageNumber % 2 !== 0) {
    return horizontal;
  }
  return horizontal === "left" ? "right" : "left";
}

export function fillTemplate(template: string, value: number, lastNumber: number): string {
  return template.replaceAll("{n}", String(value)).replaceAll("{N}", String(lastNumber));
}

/** Called after each page has been stamped, for the progress bar. */
export type PageNumberProgress = (completed: number, total: number) => void;

/**
 * Stamps page numbers onto a file and returns the new document.
 *
 * The range is clamped to the file rather than rejected, because the tool takes several
 * files at once and they need not be the same length: a range that runs off the end of a
 * shorter document numbers what it can, and one that starts past the end leaves that
 * document alone.
 */
export async function addPageNumbers(
  file: File,
  options: PageNumberOptions,
  onProgress?: PageNumberProgress,
): Promise<Blob> {
  const document = await loadPdfLibDocument(file);
  const pageCount = document.getPageCount();

  const clamped: PageNumberOptions = { ...options, toPage: Math.min(options.toPage, pageCount) };

  if (clamped.fromPage > pageCount) {
    return pdfToBlob(document);
  }

  const plan = planPageNumbers(clamped, pageCount);
  const font = await document.embedFont(standardFont(options));
  const color = hexToRgb(options.color);
  const pages = document.getPages();

  for (const [index, entry] of plan.pages.entries()) {
    stamp(pages[entry.pageNumber - 1], entry, options, font, color);
    onProgress?.(index + 1, plan.pages.length);
  }

  return pdfToBlob(document);
}

function stamp(
  page: PDFPage,
  entry: NumberedPage,
  options: PageNumberOptions,
  font: PDFFont,
  color: ReturnType<typeof rgb>,
): void {
  const text = toWinAnsi(entry.text);
  if (text === "") return;

  const { width, height } = page.getSize();
  const rotation = normalizeAngle(page.getRotation().angle);
  // A rotated page is displayed with its axes swapped, so the layout below is done in what
  // the reader sees and converted back to user space at the end.
  const visualWidth = rotation % 180 === 0 ? width : height;
  const visualHeight = rotation % 180 === 0 ? height : width;

  const size = options.size;
  const margin = MARGIN_POINTS[options.margin];
  const textWidth = font.widthOfTextAtSize(text, size);
  const ascent = font.heightAtSize(size, { descender: false });
  const descent = font.heightAtSize(size) - ascent;

  const x = horizontalAnchor(entry.horizontal, visualWidth, textWidth, margin);
  const y = verticalAnchor(options.position.vertical, visualHeight, ascent, descent, margin);

  const anchor = toUserSpace(x, y, rotation, width, height);
  page.drawText(text, {
    x: anchor.x,
    y: anchor.y,
    size,
    font,
    color,
    // Cancels the page's own rotation, so the number reads upright however the page is
    // displayed. pdf-lib rotates counter-clockwise; a viewer rotates the page clockwise.
    rotate: degrees(rotation),
  });

  if (options.underline) {
    const underlineY = y - size * 0.14;
    const start = toUserSpace(x, underlineY, rotation, width, height);
    const end = toUserSpace(x + textWidth, underlineY, rotation, width, height);
    page.drawLine({ start, end, thickness: Math.max(0.5, size * 0.055), color });
  }
}

function horizontalAnchor(
  horizontal: HorizontalPosition,
  visualWidth: number,
  textWidth: number,
  margin: number,
): number {
  if (horizontal === "left") return margin;
  if (horizontal === "right") return Math.max(margin, visualWidth - margin - textWidth);
  return Math.max(margin, (visualWidth - textWidth) / 2);
}

/** Returns the baseline, which is why the ascent and descent have to come into it. */
function verticalAnchor(
  vertical: VerticalPosition,
  visualHeight: number,
  ascent: number,
  descent: number,
  margin: number,
): number {
  if (vertical === "top") return visualHeight - margin - ascent;
  if (vertical === "middle") return (visualHeight - ascent - descent) / 2 + descent;
  return margin + descent;
}

/**
 * Converts a point in the page's visual (as-displayed) space into PDF user space.
 *
 * A viewer turns the page clockwise by its /Rotate before showing it, so for anything but an
 * upright page the coordinates a reader would point at are not the ones pdf-lib draws in.
 * `width` and `height` are the page's own, unrotated dimensions.
 */
function toUserSpace(
  x: number,
  y: number,
  rotation: number,
  width: number,
  height: number,
): { x: number; y: number } {
  switch (rotation) {
    case 90:
      return { x: width - y, y: x };
    case 180:
      return { x: width - x, y: height - y };
    case 270:
      return { x: y, y: height - x };
    default:
      return { x, y };
  }
}

const FONTS: Record<FontFamily, Record<string, StandardFonts>> = {
  helvetica: {
    regular: StandardFonts.Helvetica,
    bold: StandardFonts.HelveticaBold,
    italic: StandardFonts.HelveticaOblique,
    boldItalic: StandardFonts.HelveticaBoldOblique,
  },
  times: {
    regular: StandardFonts.TimesRoman,
    bold: StandardFonts.TimesRomanBold,
    italic: StandardFonts.TimesRomanItalic,
    boldItalic: StandardFonts.TimesRomanBoldItalic,
  },
  courier: {
    regular: StandardFonts.Courier,
    bold: StandardFonts.CourierBold,
    italic: StandardFonts.CourierOblique,
    boldItalic: StandardFonts.CourierBoldOblique,
  },
};

/**
 * Bold and italic are separate faces in PDF, not attributes, so the variant is chosen here
 * rather than being switched on at draw time.
 */
function standardFont({ font, bold, italic }: PageNumberOptions): StandardFonts {
  const variant = bold && italic ? "boldItalic" : bold ? "bold" : italic ? "italic" : "regular";
  return FONTS[font][variant];
}

const SUBSTITUTIONS: Record<string, string> = {
  "‘": "'",
  "’": "'",
  "“": '"',
  "”": '"',
  "–": "-",
  "—": "-",
  "…": "...",
};

/**
 * The 14 standard fonts can only encode WinAnsi, and pdf-lib throws rather than dropping
 * what it cannot write. Curly quotes and dashes are what a user actually pastes in, so those
 * are folded to their ASCII equivalents and anything else outside the range is dropped.
 */
function toWinAnsi(text: string): string {
  return text
    .replace(/[‘’“”–—…]/g, (char) => SUBSTITUTIONS[char])
    .replace(/[^ -~ -ÿ]/g, "")
    .trim();
}

function hexToRgb(hex: string): ReturnType<typeof rgb> {
  const value = Number.parseInt(hex.slice(1), 16);
  return rgb(((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255);
}
