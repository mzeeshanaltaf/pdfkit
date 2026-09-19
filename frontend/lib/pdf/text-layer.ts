import { loadPdfJsDocument } from "./load";

/**
 * How many pages to look at before deciding. A scanned document is scanned
 * throughout, so the first few pages answer the question, and reading every
 * page of a 400-page file just to draw a hint would cost more than the hint is
 * worth.
 */
const DEFAULT_SAMPLE = 8;

/**
 * Below this many characters a page is treated as having no real text. It is
 * not zero because a scan often carries a stray character or two — a page
 * number stamped by the scanner, or a watermark — and one glyph does not make
 * a page readable.
 */
const MIN_CHARACTERS = 12;

export interface TextLayerProbe {
  /** Pages actually looked at, which is at most the sample size. */
  checked: number;
  /** How many of those had no usable text. */
  scanned: number;
}

/**
 * Does this PDF have a text layer, or is it pictures of pages?
 *
 * It is the question that decides whether OCR is worth offering, and pdf.js can
 * answer it here without uploading anything: the document is already loaded and
 * cached per File for the thumbnails, so this costs one `getTextContent` per
 * sampled page and no extra parse.
 */
export async function probeTextLayer(
  file: File,
  sample: number = DEFAULT_SAMPLE,
): Promise<TextLayerProbe> {
  const document = await loadPdfJsDocument(file);
  const checked = Math.min(sample, document.numPages);

  let scanned = 0;
  for (let pageNumber = 1; pageNumber <= checked; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    const characters = content.items.reduce((total, item) => {
      const text = (item as { str?: string }).str ?? "";
      return total + text.trim().length;
    }, 0);
    if (characters < MIN_CHARACTERS) scanned += 1;
  }

  return { checked, scanned };
}
