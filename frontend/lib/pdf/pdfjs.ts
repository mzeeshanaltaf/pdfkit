import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
  type PDFPageProxy,
} from "pdfjs-dist";

/**
 * The worker is copied into public/ by scripts/copy-pdf-worker.mjs on postinstall, so it is
 * always served same-origin. Setting it here means every module that renders a page shares
 * one worker pool.
 */
let configured = false;

function configureWorker(): void {
  if (configured) return;
  GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
  configured = true;
}

export function loadDocument(data: Uint8Array, password?: string) {
  configureWorker();
  return getDocument({ data, password });
}

export type { PDFDocumentProxy, PDFPageProxy };
