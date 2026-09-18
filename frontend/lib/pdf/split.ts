import { PDFDocument } from "pdf-lib";

import { stripExtension } from "@/lib/format";

import { loadPdfLibDocument } from "./load";
import { pdfToBlob } from "./save";
import { zipBlobs, type ZipEntry } from "./zip";

export interface PageRange {
  /** 1-based, inclusive at both ends. */
  from: number;
  to: number;
}

export type SplitMode = "ranges" | "fixed" | "pages";

export interface SplitInput {
  mode: SplitMode;
  /** `ranges` mode: one output document per entry. */
  ranges: PageRange[];
  /** `fixed` mode: cut a new document every N pages. */
  every: number;
  /** `pages` mode: a range expression such as "1,3-5,8". */
  pages: string;
  /** Collapse every chunk into a single document instead of one file each. */
  mergeOutput: boolean;
}

/** A validation failure with a message that is safe to show the user as-is. */
export class SplitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SplitError";
  }
}

/** One output document: the pages that go in it, and the suffix its filename gets. */
export interface SplitChunk {
  label: string;
  /** 1-based page numbers, in output order. */
  pages: number[];
}

export interface SplitResult {
  blob: Blob;
  filename: string;
  /** How many PDFs came out, whether or not they ended up zipped. */
  documentCount: number;
}

/**
 * Works out what the given options produce, without touching the document itself.
 *
 * The UI calls this on every keystroke to drive the preview and the error message, so it is
 * pure and throws `SplitError` rather than returning a partial plan.
 */
export function planSplit(input: SplitInput, pageCount: number): SplitChunk[] {
  const chunks = buildChunks(input, pageCount);

  if (input.mergeOutput) {
    return [{ label: "split", pages: chunks.flatMap((chunk) => chunk.pages) }];
  }

  return chunks;
}

function buildChunks(input: SplitInput, pageCount: number): SplitChunk[] {
  switch (input.mode) {
    case "ranges":
      return validateRanges(input.ranges, pageCount).map(rangeChunk);

    case "fixed":
      return fixedRanges(input.every, pageCount).map(rangeChunk);

    case "pages":
      // Each selected page becomes its own document; "merge all" is what puts them back
      // together, which is exactly how the two checkboxes in the panel read.
      return parsePageExpression(input.pages, pageCount).map((page) => ({
        label: `page-${page}`,
        pages: [page],
      }));
  }
}

function rangeChunk(range: PageRange): SplitChunk {
  const pages: number[] = [];
  for (let page = range.from; page <= range.to; page += 1) pages.push(page);
  return {
    label: range.from === range.to ? `page-${range.from}` : `${range.from}-${range.to}`,
    pages,
  };
}

/** Checks a list of custom ranges, in the order the user entered them. */
export function validateRanges(ranges: PageRange[], pageCount: number): PageRange[] {
  if (ranges.length === 0) {
    throw new SplitError("Add at least one range.");
  }

  ranges.forEach((range, index) => {
    if (!Number.isInteger(range.from) || !Number.isInteger(range.to)) {
      throw new SplitError("Fill in the first and last page of every range.");
    }
    assertPageExists(range.from, pageCount);
    assertPageExists(range.to, pageCount);
    if (range.to < range.from) {
      throw new SplitError(
        `Range ${index + 1} ends at page ${range.to}, before it starts at page ${range.from}.`,
      );
    }
  });

  return ranges;
}

/** Turns "every N pages" into consecutive ranges covering the whole document. */
export function fixedRanges(every: number, pageCount: number): PageRange[] {
  if (!Number.isInteger(every) || every < 1) {
    throw new SplitError("Split every how many pages? Enter a whole number, 1 or more.");
  }

  const ranges: PageRange[] = [];
  for (let from = 1; from <= pageCount; from += every) {
    ranges.push({ from, to: Math.min(from + every - 1, pageCount) });
  }
  return ranges;
}

/**
 * Parses a page expression like "1,3-5,8" into the flat list of pages it names.
 *
 * Order and repeats are preserved rather than normalised: "5,1" means the user wants page 5
 * before page 1, and it is not this function's business to disagree.
 */
export function parsePageExpression(expression: string, pageCount: number): number[] {
  const trimmed = expression.trim();
  if (trimmed === "") {
    throw new SplitError("Enter the pages you want, for example 1,3-5.");
  }

  const pages: number[] = [];

  for (const rawPart of trimmed.split(",")) {
    const part = rawPart.trim();
    // A trailing comma is what a half-typed list looks like; don't shout about it.
    if (part === "") continue;

    const match = /^([0-9]+)(?:\s*-\s*([0-9]+))?$/.exec(part);
    if (!match) {
      throw new SplitError(`"${part}" is not a page number or a range like 3-5.`);
    }

    const from = Number(match[1]);
    const to = match[2] === undefined ? from : Number(match[2]);

    assertPageExists(from, pageCount);
    assertPageExists(to, pageCount);
    if (to < from) {
      throw new SplitError(`Range ${from}-${to} ends before it starts.`);
    }

    for (let page = from; page <= to; page += 1) pages.push(page);
  }

  if (pages.length === 0) {
    throw new SplitError("Enter the pages you want, for example 1,3-5.");
  }

  return pages;
}

function assertPageExists(page: number, pageCount: number): void {
  if (page < 1) {
    throw new SplitError("Page numbers start at 1.");
  }
  if (page > pageCount) {
    throw new SplitError(
      `This PDF has ${pageCount} ${pageCount === 1 ? "page" : "pages"}, so page ${page} does not exist.`,
    );
  }
}

/** Called after each output document is built, for the progress bar. */
export type SplitProgress = (completed: number, total: number) => void;

/**
 * Splits a file according to `input`. One chunk comes back as a plain PDF, several come back
 * zipped, and the caller only has to hand the blob to the download button either way.
 */
export async function splitPdf(
  file: File,
  input: SplitInput,
  onProgress?: SplitProgress,
): Promise<SplitResult> {
  const source = await loadPdfLibDocument(file);
  const chunks = planSplit(input, source.getPageCount());
  const base = stripExtension(file.name);

  const entries: ZipEntry[] = [];

  for (const [index, chunk] of chunks.entries()) {
    const output = await PDFDocument.create();
    // pdf-lib indexes pages from 0; everything user-facing in this module is 1-based.
    const copied = await output.copyPages(
      source,
      chunk.pages.map((page) => page - 1),
    );
    for (const page of copied) output.addPage(page);

    entries.push({ name: `${base}-${chunk.label}.pdf`, blob: await pdfToBlob(output) });
    onProgress?.(index + 1, chunks.length);
  }

  if (entries.length === 1) {
    return { blob: entries[0].blob, filename: entries[0].name, documentCount: 1 };
  }

  return {
    blob: await zipBlobs(entries),
    filename: `${base}-split.zip`,
    documentCount: entries.length,
  };
}
