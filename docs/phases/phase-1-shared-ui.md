# Phase 1 — Shared UI Shell

## Goal
All the reusable scaffolding every tool page will sit on top of, plus the landing page. After this phase, no PDF processing works yet, but the app looks and navigates like the real thing.

## Prerequisites
Phase 0 complete (both apps build and run).

## Tasks
1. **Tool registry** — `lib/tools.ts`: single array of `{ id, slug, name, tagline, description, icon, accent, multiple, ctaLabel }` for all 10 tools. This is the one source of truth — landing grid, header nav, per-page `generateMetadata`, and "continue to another tool" links all read from it.
2. **Layout** — header (logo/name "PDFKit", nav), footer. Distinct color palette via a single accent token in the Tailwind theme (not iLovePDF red). Use the `design-taste-frontend` skill for visual design decisions; use `nextjs-best-practices` / `vercel-react-best-practices` where relevant for component structure and performance.
3. **Landing page** (`/`) — hero (name, one-line pitch, "runs privately in your browser where possible"), grid of 10 `ToolCard`s (icon, name, tagline) driven by the registry, footer.
4. **`ToolShell.tsx`** (`components/tool/`) — the state machine `select → configure → processing → done | error`. Owns the file list state shape `{ id, file, name, size, pageCount, thumbnail, rotation, error }`, add/remove handlers, CTA wiring. Renders the three-column layout: main canvas (file/page grid) + fixed-width right sidebar (title, options, CTA pinned to bottom). Sidebar stacks below the grid under `lg` breakpoint.
5. **`FileDropzone.tsx`** — full-page "Select PDF files" + drag-and-drop via react-dropzone. Enforces `.pdf` extension, single vs multiple per tool config, and a 50 MB cap for backend-bound tools.
6. **`FileGrid.tsx` / `FileCard.tsx`** — sortable (dnd-kit) cards: first-page thumbnail, name, size, remove button, optional per-card action overlay slot (used later by Rotate).
7. **`PageGrid.tsx` / `PageCard.tsx`** — page-level thumbnails for Organize/Split/Page Numbers; sortable; hover actions (rotate, delete); lazy thumbnail rendering via IntersectionObserver for large documents.
8. **`AddFilesButton.tsx`** (floating "+" with count badge), **`SortButton.tsx`** (A→Z / Z→A).
9. **`OptionsSidebar.tsx`** — title, info callout, children slot, CTA button.
10. **`ProcessingView.tsx`** — upload progress bar (XHR-based) then indeterminate "Processing…" state.
11. **`ResultView.tsx`** — download button, optional size before/after, "Start over", "Continue to: …" links sourced from the tool registry.
12. **Browser PDF loading** (`lib/pdf/load.ts`) — `File` → `PDFDocument` (pdf-lib) + `PDFDocumentProxy` (pdf.js); detect encrypted PDFs.
13. **`lib/pdf/thumbnails.ts`** — render page N to a small JPEG data URL via pdf.js canvas, cached per file+page+rotation.
14. **Encrypted-PDF guard** — shared component/hook: when a browser-side tool hits a password error loading a PDF, show "This PDF is password protected" with a link to `/unlock-pdf`.
15. Remember the global hydration rule: any workspace component using `crypto.randomUUID()`, canvas, or File APIs at init must be loaded via `next/dynamic` with `{ ssr: false }`.

## Out of scope
No actual merge/split/etc. logic. Tool pages can exist as placeholders that mount `ToolShell` with no-op processing, just to prove the shell works end to end with a fake "done" state.

## Verification
- `npm run lint && npm run build` clean.
- Landing page renders 10 cards from the registry; clicking one navigates to a stub tool route.
- On a stub tool route: drag/drop or select PDFs, see thumbnails in the grid, reorder via drag, remove a file, hit CTA → fake processing → fake result screen with working "Start over".
- Encrypted PDF dropped in → guard message appears with a link to `/unlock-pdf`.
- Resize to mobile width — sidebar stacks below grid, no horizontal scroll.

## Definition of done
Shell, dropzone, grids, thumbnails, and result flow all work generically; landing page complete; `STATUS.md` updated.
