import { degrees } from "pdf-lib";

import { loadPdfLibDocument } from "./load";
import { pdfToBlob } from "./save";

/**
 * Turns every page of a file by `delta` degrees on top of whatever rotation it already has.
 *
 * A page's `/Rotate` is absolute, not relative, so the existing angle has to be read and
 * added to rather than overwritten, or a page that was already sideways would snap upright.
 */
export async function rotatePdf(file: File, delta: number): Promise<Blob> {
  const document = await loadPdfLibDocument(file);

  if (normalizeAngle(delta) !== 0) {
    for (const page of document.getPages()) {
      page.setRotation(degrees(normalizeAngle(page.getRotation().angle + delta)));
    }
  }

  return pdfToBlob(document);
}

/**
 * Folds an angle into 0/90/180/270. Rounding to the nearest quarter turn matters because
 * `/Rotate` is only required to be a multiple of 90 in practice, not in every file found in
 * the wild, and pdf-lib rejects anything else.
 */
export function normalizeAngle(angle: number): number {
  return ((Math.round(angle / 90) % 4) + 4) % 4 * 90;
}
