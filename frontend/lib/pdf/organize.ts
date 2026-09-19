import { degrees, PDFDocument, type PDFPage } from "pdf-lib";

import { loadPdfLibDocument } from "./load";
import { normalizeAngle } from "./rotate";
import { pdfToBlob } from "./save";

/**
 * One page of the document being built. `fileId` is null for a blank page the user
 * inserted, which has no source document behind it.
 */
export interface OrganizeItem {
  fileId: string | null;
  /** 1-based page number inside its source file; ignored for a blank page. */
  pageNumber: number;
  /** Extra rotation in degrees on top of the page's existing /Rotate. */
  rotation: number;
}

export interface OrganizeSource {
  id: string;
  file: File;
}

/** Called after each page has been added, for the progress bar. */
export type OrganizeProgress = (completed: number, total: number) => void;

/** Fallback size for a blank page inserted into a document with no readable pages. */
const A4_POINTS: [number, number] = [595.28, 841.89];

/**
 * Builds a new document from an explicit list of pages.
 *
 * The list is the whole model of the tool: it can span several files, name the same page
 * twice, leave pages out, carry a per-page rotation, and include blanks. Pages are copied
 * with `copyPages`, which deep-copies the fonts and images each one references, so the
 * result does not depend on the source documents staying alive.
 */
export async function organizePdf(
  items: OrganizeItem[],
  sources: OrganizeSource[],
  onProgress?: OrganizeProgress,
): Promise<Blob> {
  if (items.length === 0) {
    throw new Error("The new document has no pages in it.");
  }

  const output = await PDFDocument.create();
  const filesById = new Map(sources.map((source) => [source.id, source.file]));

  // Each source document is opened once and all of its wanted pages are copied in a single
  // call, rather than re-parsing the file for every page the user kept from it.
  const wanted = new Map<string, number[]>();
  for (const item of items) {
    if (item.fileId === null) continue;
    const indices = wanted.get(item.fileId) ?? [];
    // pdf-lib indexes pages from 0; everything user-facing in this module is 1-based.
    indices.push(item.pageNumber - 1);
    wanted.set(item.fileId, indices);
  }

  const queues = new Map<string, { pages: PDFPage[]; taken: number }>();
  for (const [fileId, indices] of wanted) {
    const file = filesById.get(fileId);
    if (!file) {
      throw new Error("One of the files this document was built from is no longer loaded.");
    }
    const source = await loadPdfLibDocument(file);
    // Repeats are intentional: naming a page twice copies it twice.
    queues.set(fileId, { pages: await output.copyPages(source, indices), taken: 0 });
  }

  const blankSize = firstPageSize(queues);

  for (const [index, item] of items.entries()) {
    if (item.fileId === null) {
      // A blank page takes the shape of the document's first real page, so inserting one
      // into a letter-sized document does not produce a stray A4 sheet.
      output.addPage(blankSize);
    } else {
      const queue = queues.get(item.fileId);
      if (!queue) throw new Error("A page went missing while the document was being built.");
      const page = queue.pages[queue.taken];
      queue.taken += 1;
      output.addPage(page);
      if (normalizeAngle(item.rotation) !== 0) {
        // /Rotate is absolute, so the page's existing angle is added to, not overwritten.
        page.setRotation(degrees(normalizeAngle(page.getRotation().angle + item.rotation)));
      }
    }

    onProgress?.(index + 1, items.length);
  }

  return pdfToBlob(output);
}

function firstPageSize(queues: Map<string, { pages: PDFPage[] }>): [number, number] {
  for (const queue of queues.values()) {
    const page = queue.pages[0];
    if (page) {
      const { width, height } = page.getSize();
      return [width, height];
    }
  }
  return A4_POINTS;
}
