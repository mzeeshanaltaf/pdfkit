import type { ToolFile, ToolPage } from "@/components/tool/types";
import type { SortDirection } from "@/components/tool/use-tool-files";
import type { OrganizeItem, OrganizeSource } from "@/lib/pdf/organize";

/**
 * The whole editable state of the Organize workspace.
 *
 * It lives in the workspace component rather than inside `ToolShell`, because the CTA's
 * `process` callback needs to read it, and every operation below is a pure function of it —
 * the same arrangement Split uses for its ranges.
 */
export interface OrganizeState {
  pages: ToolPage[];
  /** Pages the user deleted, remembered so a later re-sync cannot resurrect them. */
  deleted: string[];
  /** The file list `pages` was last built against; see `syncOrganize`. */
  signature: string;
}

export function createOrganizeState(): OrganizeState {
  return { pages: [], deleted: [], signature: "" };
}

/** Changes whenever the page list would need rebuilding: files added, removed or read. */
export function fileSignature(files: ToolFile[]): string {
  return files
    .map((file) => `${file.id}:${file.pageCount ?? "?"}:${file.error ? "x" : ""}`)
    .join(",");
}

/** Every page of every readable file, in the order the files are listed. */
function naturalPages(files: ToolFile[]): ToolPage[] {
  const pages: ToolPage[] = [];
  for (const file of files) {
    if (file.error || file.pageCount === null) continue;
    for (let pageNumber = 1; pageNumber <= file.pageCount; pageNumber += 1) {
      pages.push({ id: `${file.id}#${pageNumber}`, fileId: file.id, pageNumber, rotation: 0 });
    }
  }
  return pages;
}

/**
 * Brings the page list back in step with the file list, preserving the user's edits: pages
 * they reordered, rotated or deleted keep their state, pages from a file just added are
 * appended, and pages from a removed file disappear.
 *
 * It is pure and idempotent, so the canvas, the options panel and the process callback can
 * each call it and are guaranteed to be looking at the same document.
 */
export function syncOrganize(state: OrganizeState, files: ToolFile[]): OrganizeState {
  const signature = fileSignature(files);
  if (signature === state.signature) return state;

  const desired = naturalPages(files);
  // Emptying the workspace resets it: blank pages and deletions from a document that is no
  // longer loaded have nothing left to mean.
  if (desired.length === 0) return { pages: [], deleted: [], signature };

  const desiredIds = new Set(desired.map((page) => page.id));
  const known = new Set(state.pages.map((page) => page.id));
  const deleted = new Set(state.deleted);

  return {
    pages: [
      ...state.pages.filter((page) => page.fileId === null || desiredIds.has(page.id)),
      ...desired.filter((page) => !known.has(page.id) && !deleted.has(page.id)),
    ],
    deleted: state.deleted,
    signature,
  };
}

export function movePage(state: OrganizeState, activeId: string, overId: string): OrganizeState {
  if (activeId === overId) return state;
  const from = state.pages.findIndex((page) => page.id === activeId);
  const to = state.pages.findIndex((page) => page.id === overId);
  if (from === -1 || to === -1) return state;

  const pages = [...state.pages];
  const [moved] = pages.splice(from, 1);
  pages.splice(to, 0, moved);
  return { ...state, pages };
}

export function rotatePage(state: OrganizeState, id: string): OrganizeState {
  return {
    ...state,
    pages: state.pages.map((page) =>
      page.id === id ? { ...page, rotation: (page.rotation + 90) % 360 } : page,
    ),
  };
}

export function deletePage(state: OrganizeState, id: string): OrganizeState {
  return {
    ...state,
    pages: state.pages.filter((page) => page.id !== id),
    // Blank pages are not remembered: they only exist in this list, so removing one is the
    // end of it, and holding the id would leak an entry per insert-then-delete.
    deleted: id.startsWith(BLANK_PREFIX) ? state.deleted : [...state.deleted, id],
  };
}

const BLANK_PREFIX = "blank-";

/** Adds a blank page after `id`, or at the end when `id` is null. */
export function insertBlankAfter(state: OrganizeState, id: string | null): OrganizeState {
  const blank: ToolPage = {
    id: `${BLANK_PREFIX}${crypto.randomUUID()}`,
    fileId: null,
    pageNumber: 0,
    rotation: 0,
  };

  const index = id === null ? -1 : state.pages.findIndex((page) => page.id === id);
  if (index === -1) return { ...state, pages: [...state.pages, blank] };

  const pages = [...state.pages];
  pages.splice(index + 1, 0, blank);
  return { ...state, pages };
}

/**
 * Sorts by where each page came from: file order first, then page number. Blank pages have
 * no place in that order, so they keep theirs relative to each other and go last.
 */
export function sortPages(
  state: OrganizeState,
  files: ToolFile[],
  direction: SortDirection,
): OrganizeState {
  const order = new Map(files.map((file, index) => [file.id, index]));
  const real = state.pages.filter((page) => page.fileId !== null);
  const blanks = state.pages.filter((page) => page.fileId === null);

  real.sort((a, b) => {
    const byFile = (order.get(a.fileId!) ?? 0) - (order.get(b.fileId!) ?? 0);
    const compared = byFile !== 0 ? byFile : a.pageNumber - b.pageNumber;
    return direction === "asc" ? compared : -compared;
  });

  return { ...state, pages: [...real, ...blanks] };
}

/** Back to every page of every loaded file, upright and in file order. */
export function resetOrganize(files: ToolFile[]): OrganizeState {
  return { pages: naturalPages(files), deleted: [], signature: fileSignature(files) };
}

/** Flattens the grid into the list `organizePdf` builds a document from. */
export function toOrganizeItems(pages: ToolPage[]): OrganizeItem[] {
  return pages.map((page) => ({
    fileId: page.fileId,
    pageNumber: page.pageNumber,
    rotation: page.rotation,
  }));
}

export function toOrganizeSources(files: ToolFile[]): OrganizeSource[] {
  return files.map((file) => ({ id: file.id, file: file.file }));
}

/** How many pages each loaded file still has in the grid, for the sidebar's file list. */
export function pageCountsByFile(pages: ToolPage[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const page of pages) {
    if (page.fileId === null) continue;
    counts.set(page.fileId, (counts.get(page.fileId) ?? 0) + 1);
  }
  return counts;
}
