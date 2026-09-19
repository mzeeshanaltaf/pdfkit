import { stripExtension } from "@/lib/format";

import { loadPdfJsDocument } from "./load";
import { zipBlobs, type ZipEntry } from "./zip";

export type JpgQuality = "normal" | "high";

export interface JpgQualitySpec {
  label: string;
  /** Multiplier on the page's natural 72 dpi size. */
  scale: number;
  /** JPEG encoder quality, 0-1. */
  quality: number;
  /** What the scale works out to in dots per inch, for the panel's help text. */
  dpi: number;
}

export const JPG_QUALITIES: Record<JpgQuality, JpgQualitySpec> = {
  normal: { label: "Normal", scale: 2, quality: 0.85, dpi: 144 },
  high: { label: "High", scale: 3, quality: 0.92, dpi: 216 },
};

/**
 * Browsers cap how large a canvas may be, and the limit is lower than it looks: Safari in
 * particular refuses anything over roughly 4096 on an edge before it starts returning blank
 * bitmaps. Capping the longest edge keeps a poster-sized page from silently rendering black
 * at High quality, at the cost of a little resolution on pages nobody prints at that size.
 */
const MAX_EDGE_PX = 8000;

export interface JpgSource {
  /** Stable id for the source file; only used to build the output filenames. */
  id: string;
  name: string;
  file: File;
}

/** Called after each page has been encoded, for the progress bar. */
export type JpgProgress = (completed: number, total: number) => void;

export interface PdfToJpgResult {
  blob: Blob;
  filename: string;
  imageCount: number;
}

export interface PdfToJpgOptions {
  quality?: JpgQuality;
  onProgress?: JpgProgress;
  signal?: AbortSignal;
}

/**
 * Renders every page of every given file to a JPEG.
 *
 * One page comes back as a plain image and anything more comes back zipped, so the caller
 * hands the blob to the download button either way — the same shape `splitPdf` uses.
 */
export async function pdfToJpg(
  sources: JpgSource[],
  { quality = "normal", onProgress, signal }: PdfToJpgOptions = {},
): Promise<PdfToJpgResult> {
  if (sources.length === 0) {
    throw new Error("Add a PDF to convert.");
  }

  const spec = JPG_QUALITIES[quality];
  const documents = [];
  let total = 0;

  // Every document is opened first so the total page count — and therefore the progress
  // bar — is known before the slow part starts.
  for (const source of sources) {
    const doc = await loadPdfJsDocument(source.file);
    documents.push({ source, doc });
    total += doc.numPages;
  }

  const entries: ZipEntry[] = [];
  const padding = String(total).length;

  for (const { source, doc } of documents) {
    const base = stripExtension(source.name);

    for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
      throwIfAborted(signal);
      const page = await doc.getPage(pageNumber);

      try {
        const blob = await renderPageToJpeg(page, spec);
        entries.push({
          // Zero-padded so the images sort in page order in the extracted folder, where a
          // plain "page-10" would otherwise land between "page-1" and "page-2".
          name: `${base}-page-${String(pageNumber).padStart(padding, "0")}.jpg`,
          blob,
        });
      } finally {
        page.cleanup();
      }

      onProgress?.(entries.length, total);
    }
  }

  if (entries.length === 1) {
    return { blob: entries[0].blob, filename: entries[0].name, imageCount: 1 };
  }

  const zipName =
    sources.length === 1 ? `${stripExtension(sources[0].name)}-jpg.zip` : "pdf-to-jpg.zip";

  return { blob: await zipBlobs(entries), filename: zipName, imageCount: entries.length };
}

type PdfJsPage = Awaited<ReturnType<Awaited<ReturnType<typeof loadPdfJsDocument>>["getPage"]>>;

async function renderPageToJpeg(page: PdfJsPage, spec: JpgQualitySpec): Promise<Blob> {
  // No `rotation` here on purpose: pdf.js defaults the viewport to the page's own /Rotate,
  // so a sideways page is rendered the way a reader would see it.
  const natural = page.getViewport({ scale: 1 });
  const scale = Math.min(spec.scale, MAX_EDGE_PX / Math.max(natural.width, natural.height));
  const viewport = page.getViewport({ scale });

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(viewport.width));
  canvas.height = Math.max(1, Math.floor(viewport.height));

  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable in this browser.");
  // JPEG has no alpha channel, so anything transparent would encode as black without this.
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);

  try {
    await page.render({ canvas, viewport }).promise;
    return await canvasToJpeg(canvas, spec.quality);
  } finally {
    // Converting a long document allocates a full-size bitmap per page; zeroing the canvas
    // lets each one go as soon as its JPEG exists instead of at the next major GC.
    canvas.width = 0;
    canvas.height = 0;
  }
}

function canvasToJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("The browser could not encode this page as a JPG."));
      },
      "image/jpeg",
      quality,
    );
  });
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
}
