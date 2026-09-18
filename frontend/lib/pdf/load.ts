import { EncryptedPDFError, PDFDocument } from "pdf-lib";

import { loadDocument, type PDFDocumentProxy } from "./pdfjs";

export type PdfErrorKind = "encrypted" | "invalid" | "too-large";

/** A load failure we can show a specific message for, rather than a raw stack. */
export class PdfLoadError extends Error {
  readonly kind: PdfErrorKind;

  constructor(kind: PdfErrorKind, message: string) {
    super(message);
    this.name = "PdfLoadError";
    this.kind = kind;
  }
}

const MESSAGES: Record<PdfErrorKind, string> = {
  encrypted: "This PDF is password protected.",
  invalid: "This file could not be read as a PDF.",
  "too-large": "This file is too large.",
};

export function pdfErrorMessage(kind: PdfErrorKind): string {
  return MESSAGES[kind];
}

function isPasswordError(error: unknown): boolean {
  if (error instanceof EncryptedPDFError) return true;
  if (typeof error !== "object" || error === null) return false;
  const { name, message } = error as { name?: string; message?: string };
  return name === "PasswordException" || /password/i.test(message ?? "");
}

/**
 * pdf-lib only raises EncryptedPDFError when it gets far enough to read the trailer. With
 * AES-256 files written by qpdf it trips over an encrypted object first and throws a plain
 * parse error, so the bytes are checked directly before calling a file corrupt.
 */
function hasEncryptDictionary(bytes: Uint8Array): boolean {
  const needle = "/Encrypt";
  const text = new TextDecoder("latin1").decode(bytes);
  return text.includes(needle);
}

function toPdfLoadError(error: unknown, bytes?: Uint8Array): PdfLoadError {
  if (error instanceof PdfLoadError) return error;
  const encrypted = isPasswordError(error) || (bytes ? hasEncryptDictionary(bytes) : false);
  const kind: PdfErrorKind = encrypted ? "encrypted" : "invalid";
  return new PdfLoadError(kind, MESSAGES[kind]);
}

/** Each engine needs its own copy: pdf.js takes ownership of the buffer it is handed. */
async function readBytes(file: File): Promise<Uint8Array> {
  return new Uint8Array(await file.arrayBuffer());
}

/**
 * pdf.js documents are expensive (each holds a worker port), so one is cached per File
 * object and reused by the thumbnail renderer and by tools that read page geometry.
 */
const documentCache = new WeakMap<File, Promise<PDFDocumentProxy>>();

export function loadPdfJsDocument(file: File): Promise<PDFDocumentProxy> {
  const cached = documentCache.get(file);
  if (cached) return cached;

  const pending = (async () => {
    try {
      return await loadDocument(await readBytes(file)).promise;
    } catch (error) {
      documentCache.delete(file);
      throw toPdfLoadError(error);
    }
  })();

  documentCache.set(file, pending);
  return pending;
}

/** Tears down the worker port for a file the user removed from the list. */
export async function releasePdfJsDocument(file: File): Promise<void> {
  const cached = documentCache.get(file);
  if (!cached) return;
  documentCache.delete(file);
  try {
    const doc = await cached;
    // Tearing down the loading task is what releases the worker port behind the document.
    await doc.loadingTask.destroy();
  } catch {
    // The document never loaded; nothing to release.
  }
}

/** Loads a file with pdf-lib, which is what the browser-side tools edit and save. */
export async function loadPdfLibDocument(file: File): Promise<PDFDocument> {
  const bytes = await readBytes(file);
  try {
    return await PDFDocument.load(bytes, { ignoreEncryption: false });
  } catch (error) {
    throw toPdfLoadError(error, bytes);
  }
}

export interface PdfInfo {
  pageCount: number;
}

/** Cheap "can we open this, and how many pages" probe used when a file is added. */
export async function inspectPdf(file: File): Promise<PdfInfo> {
  const doc = await loadPdfJsDocument(file);
  return { pageCount: doc.numPages };
}
