# Phase 3 — Browser Tools, Batch 2: PDF to JPG (page mode), Organize, Page Numbers

## Goal
Remaining three browser-only tools. These are the most complex client-side tools (multi-file page-level manipulation, precise coordinate math), so they're kept separate from the simpler Batch 1.

## Prerequisites
Phase 2 complete (Merge/Rotate/Split live; `lib/pdf/` conventions established).

## Tasks

### 1. PDF to JPG — page mode (`/pdf-to-jpg`)
- `lib/pdf/pdfToJpg.ts` — render each page with pdf.js at scale 2 (Normal, ≈144 dpi, quality 0.85) or scale 3 (High, ≈216 dpi, quality 0.92), `canvas.toBlob("image/jpeg")`, zip when more than one image.
- `components/tools/pdf-to-jpg/` — mode cards: **Page to JPG** (shows "N JPG will be created", live count from loaded page total) and **Extract images** (routes to backend — stub only in this phase, wired for real in Phase 5). Quality toggle Normal (default) / High.
- Only the Page-to-JPG path needs to work end-to-end in this phase; Extract-images mode can show a "coming soon" or be visually present but disabled until Phase 5.

### 2. Organize (`/organize-pdf`)
- `lib/pdf/organize.ts` — input is an ordered list `[{ fileId, pageIndex, rotation }]` spanning one or more files; builds a new document from that order. Supports reorder, rotate, delete, sort, reset, and "insert blank page".
- `components/tools/organize/` — sidebar lists files (labelled A, B, C… with a colour chip per file) and "Reset all"; page grid (reuses `PageGrid`/`PageCard` from Phase 1) with reorder/rotate/delete, sort asc/desc, insert-blank-page action. CTA "Organize".
- Multi-file input: pages from all loaded files appear in one combined grid, each tagged with its source file's colour/letter.

### 3. Page Numbers (`/add-page-numbers`)
- `lib/pdf/pageNumbers.ts` — options: `mode` single/facing, `position` (9-cell grid), `margin` small/recommended/big, `firstNumber`, `fromPage`/`toPage`, `template` (`{n}` / `Page {n}` / `Page {n} of {N}` / custom with `{n}`/`{N}`), `font` Helvetica/Times/Courier, `size`, bold/italic (font variant selection), underline (drawn line under text), `color` hex. Facing mode mirrors the horizontal position on even pages. Must account for existing page rotation when computing draw coordinates (rotated pages need transformed x/y).
- `components/tools/page-numbers/` — file selector dropdown when multiple files loaded (for preview target); full options panel per above. Live preview: red dot overlay on the relevant thumbnail showing the chosen position, matching the iLovePDF reference screenshots. CTA "Add page numbers".

## Verification (manual, using fixtures from `frontend/test-fixtures/`)
- PDF→JPG: Normal vs High quality → output image dimensions visibly differ; single page → single JPG download, multi-page → ZIP.
- Organize: combine two files, reorder across files, delete a page, rotate a page, insert a blank page → resulting PDF matches the final grid order exactly.
- Page numbers: bottom-right position, template "Page {n} of {N}", facing mode on, starting from page 2 → open output, confirm text present and mirrored on even pages, rotated pages (if tested) still show upright numbers in the right spot.
- `npm run lint && npm run build` clean.

## Definition of done
All 6 browser-only tools (Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG page mode) fully functional; `STATUS.md` updated — this marks all client-side processing complete.
