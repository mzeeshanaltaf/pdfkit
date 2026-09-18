import { PDFDocument } from "pdf-lib";

import { loadPdfLibDocument } from "./load";
import { pdfToBlob } from "./save";

/** Called after each source file has been copied in, for the progress bar. */
export type MergeProgress = (completed: number, total: number) => void;

/**
 * Concatenates the given files into one document, in the order they are passed.
 *
 * `copyPages` is what makes this safe across documents: it deep-copies each page along with
 * the fonts and images it references, so nothing depends on the source document staying
 * alive once this returns.
 */
export async function mergePdfs(files: File[], onProgress?: MergeProgress): Promise<Blob> {
  if (files.length < 2) {
    throw new Error("Merging needs at least two PDFs.");
  }

  const merged = await PDFDocument.create();

  for (const [index, file] of files.entries()) {
    const source = await loadPdfLibDocument(file);
    const pages = await merged.copyPages(source, source.getPageIndices());
    for (const page of pages) merged.addPage(page);
    onProgress?.(index + 1, files.length);
  }

  return pdfToBlob(merged);
}
