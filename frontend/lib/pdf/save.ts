import type { PDFDocument } from "pdf-lib";

/**
 * Serialises a pdf-lib document to a downloadable blob.
 *
 * `useObjectStreams` is left on: it is what keeps a merged or split file close to the size
 * of its inputs instead of inflating every cross-reference entry.
 */
export async function pdfToBlob(document: PDFDocument): Promise<Blob> {
  const bytes = await document.save();
  // pdf-lib types its result as Uint8Array<ArrayBufferLike>, and TS will not take that as a
  // BlobPart because the union admits SharedArrayBuffer. It never is one here: pdf-lib
  // allocates the buffer itself. Asserting beats copying a file that can run to 50 MB.
  return new Blob([bytes as Uint8Array<ArrayBuffer>], { type: "application/pdf" });
}
