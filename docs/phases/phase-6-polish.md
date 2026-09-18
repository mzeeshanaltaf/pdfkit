# Phase 6 — Polish

## Goal
All 10 tools work by Phase 5; this phase is about correctness under edge cases, responsive layout, and finishing touches before deploy.

## Prerequisites
Phase 5 complete — every tool functional end-to-end locally.

## Tasks
1. **Responsive pass** — walk every one of the 10 tool pages plus the landing page at mobile width. Sidebar-stacks-below-grid behavior (built in Phase 1) should hold everywhere; check dropzone, file cards, and result view don't overflow or clip on small screens.
2. **Per-tool metadata** — `generateMetadata` per route reading from the `lib/tools.ts` registry (title, description, OG tags) for all 10 tool pages + landing.
3. **Encrypted-file guard coverage** — confirm the Phase 1 guard fires correctly on *every* browser-side tool (Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG page mode), not just the one it was first tested on.
4. **Empty / error states**:
   - No files selected yet (initial dropzone state) on every tool.
   - Processing failure (browser-side exception, e.g. corrupt PDF) shows a clear message with a way to retry or start over.
   - Backend 5xx / network failure shows a toast, doesn't leave the UI stuck in "Processing…".
5. **Favicon and app icons** — add favicon, OG image, apple-touch-icon using the "PDFKit" branding decided in Phase 1.
6. **Cross-tool consistency check** — CTA labels, button placement, spacing, and copy tone match across all 10 tools (this is where inconsistencies between tools built in different phases tend to surface).
7. **Accessibility pass** — keyboard navigation through file grids and option panels, visible focus states, sufficient color contrast on the accent palette.

## Verification
Full manual matrix across three fixtures kept in `frontend/test-fixtures/` (multi-page text PDF, scanned image-only PDF, password-protected PDF):
- Merge two files, reorder, sort → correct page order.
- Split: custom ranges, fixed every 2, pages `"1,3-5"` merged → all correct.
- Rotate right twice then reset; per-file rotate → verified in a viewer.
- Organize two files: reorder, delete, rotate, insert blank page → output matches the grid.
- Page numbers: bottom-right, `"Page {n} of {N}"`, facing mode, from page 2 → text present and mirrored correctly.
- PDF→JPG normal/high → dimensions differ; extract images → ZIP has embedded images.
- Compress all three levels → extreme < recommended < less; all open fine.
- Protect with password → viewer prompts for password; Unlock (with and without password paths) succeeds.
- OCR the scanned PDF → text becomes selectable/searchable.
- Encrypted PDF dropped on every browser tool → guard message links to Unlock, every time.
- Non-PDF and >50 MB upload rejected with a clear message, on every relevant tool.
- `npm run lint && npm run build` clean; no console errors/warnings on any of the 11 pages (10 tools + landing).

## Definition of done
Every item in the manual matrix passes; app is deploy-ready; `STATUS.md` updated.
