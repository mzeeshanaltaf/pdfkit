import { loadPdfJsDocument } from "./load";

export interface ThumbnailOptions {
  /** Longest edge of the rendered bitmap, in CSS pixels. */
  maxSize?: number;
  /** Extra rotation applied on top of the page's own /Rotate value. */
  rotation?: number;
  quality?: number;
}

const DEFAULT_MAX_SIZE = 260;
const DEFAULT_QUALITY = 0.72;

/**
 * Rendering the same page twice is common (a card re-mounts, a grid re-orders), so results
 * are memoised per file + page + rotation. In-flight renders are cached too, which keeps a
 * fast scroll through a long document from queueing the same page several times over.
 */
const cache = new Map<string, Promise<string>>();

function cacheKey(fileKey: string, pageNumber: number, rotation: number, maxSize: number): string {
  return `${fileKey}:${pageNumber}:${rotation}:${maxSize}`;
}

/**
 * Renders one page to a JPEG data URL.
 *
 * `fileKey` is the caller's stable id for the file (the ToolFile id), so two different files
 * with the same name never share a cache entry.
 */
export function renderThumbnail(
  fileKey: string,
  file: File,
  pageNumber: number,
  options: ThumbnailOptions = {},
): Promise<string> {
  const {
    maxSize = DEFAULT_MAX_SIZE,
    rotation = 0,
    quality = DEFAULT_QUALITY,
  } = options;

  const key = cacheKey(fileKey, pageNumber, normalizeRotation(rotation), maxSize);
  const cached = cache.get(key);
  if (cached) return cached;

  const pending = render(file, pageNumber, normalizeRotation(rotation), maxSize, quality).catch(
    (error) => {
      // A failed render must not be remembered, or a retry can never succeed.
      cache.delete(key);
      throw error;
    },
  );

  cache.set(key, pending);
  return pending;
}

async function render(
  file: File,
  pageNumber: number,
  rotation: number,
  maxSize: number,
  quality: number,
): Promise<string> {
  const doc = await loadPdfJsDocument(file);
  const page = await doc.getPage(pageNumber);

  try {
    const base = page.getViewport({ scale: 1, rotation: page.rotate + rotation });
    const scale = Math.min(maxSize / base.width, maxSize / base.height, 4);
    const viewport = page.getViewport({ scale, rotation: page.rotate + rotation });

    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.floor(viewport.width));
    canvas.height = Math.max(1, Math.floor(viewport.height));

    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable in this browser.");
    // PDFs assume white paper; without this, transparent areas render black in the JPEG.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);

    await page.render({ canvas, viewport }).promise;
    return canvas.toDataURL("image/jpeg", quality);
  } finally {
    page.cleanup();
  }
}

function normalizeRotation(rotation: number): number {
  return ((rotation % 360) + 360) % 360;
}

/** Drops every cached render for a file, used when the file leaves the workspace. */
export function clearThumbnailCache(fileKey: string): void {
  const prefix = `${fileKey}:`;
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
}
