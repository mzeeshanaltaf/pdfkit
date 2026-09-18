# Phase 2 — Browser Tools, Batch 1: Merge, Rotate, Split

## Goal
First three real, fully-working, browser-only tools, wired into `ToolShell` from Phase 1.

## Prerequisites
Phase 1 complete (shell, dropzone, grids, thumbnails, result view all working generically).

## Tasks

### 1. Merge (`/merge-pdf`)
- `lib/pdf/merge.ts` — `PDFDocument.create()`, `copyPages` in user-defined order.
- `components/tools/merge/` — sidebar with file order (drag via `FileGrid`), `SortButton`, info callout. CTA "Merge PDF".
- Multiple files required; reuses `FileGrid` reordering from Phase 1.

### 2. Rotate (`/rotate-pdf`)
- `lib/pdf/rotate.ts` — apply rotation delta (90/180/270) to every page: `page.setRotation(degrees(current + delta))`.
- `components/tools/rotate/` — sidebar RIGHT/LEFT buttons apply to all files; hovering a file card shows a rotate icon for per-file rotation (uses the `FileCard` action-overlay slot from Phase 1); thumbnail rotates live; "Reset all" button.
- Output: single PDF if one file, ZIP if multiple (use `lib/pdf/zip.ts` from Phase 1's shared helpers, or add now if not yet created).

### 3. Split (`/split-pdf`)
- `lib/pdf/split.ts` — inputs: `{ mode: "ranges" | "fixed" | "pages", ranges: [{from,to}], every: N, pages: "1,3-5", mergeOutput: boolean }`. Produces one PDF or a ZIP. Includes a range-expression parser (`"1,3-5,8"`) with validation against actual page count and clear error messages for invalid input.
- `components/tools/split/` — tabs Range | Pages. Range tab: mode Custom (list of from/to ranges with "Add range"/remove) or Fixed (every N pages); checkbox "Merge all ranges in one PDF". Pages tab: Extract all / Select pages (`1,3-5`) with the same merge checkbox. Preview groups thumbnails per range (first…last page shown). CTA "Split PDF". (No "Size" mode — that's iLovePDF's premium feature, intentionally omitted.)

### 4. Shared helpers (add if not already present from Phase 1)
- `lib/pdf/zip.ts`, `lib/pdf/download.ts`.

## Verification (manual, using `frontend/test-fixtures/` multi-page text PDF — create this fixture now if it doesn't exist)
- Merge two files, reorder, sort A→Z → open output PDF, confirm page order is correct.
- Rotate right twice then reset on one file; per-file rotate on a multi-file set → open in a viewer and confirm rotation.
- Split: custom ranges → ZIP contents match ranges; fixed every 2 pages → correct file count; pages `"1,3-5"` with merge checked → single PDF with exactly those pages in order.
- Encrypted PDF dropped on Merge → guard message from Phase 1 fires correctly.
- `npm run lint && npm run build` clean.

## Definition of done
Merge, Rotate, Split fully functional and manually verified; `STATUS.md` updated with which tools are live.
