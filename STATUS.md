# Status

Last updated: 2026-09-18 (Phase 2)

## Current phase

**Phase 2 — Browser tools batch 1** — ✅ complete. Next up: **Phase 3 — Browser tools batch 2
(PDF→JPG page mode, Organize, Page numbers)**.

See [`docs/phases/phase-3-browser-tools-2.md`](docs/phases/phase-3-browser-tools-2.md) for
the task list.

## Tools live so far

| Tool | Route | State |
|---|---|---|
| Merge PDF | `/merge-pdf` | ✅ real, browser-side |
| Rotate PDF | `/rotate-pdf` | ✅ real, browser-side |
| Split PDF | `/split-pdf` | ✅ real, browser-side |
| the other seven | — | placeholder workspace (returns the first file unchanged) |

## Phase checklist

- [x] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [x] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [x] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
- [ ] Phase 3 — Browser tools batch 2 (PDF→JPG page mode, Organize, Page Numbers)
- [ ] Phase 4 — Backend services (Compress, Protect, Unlock, OCR, Extract images) + tests
- [ ] Phase 5 — Wire backend tools into UI
- [ ] Phase 6 — Polish (responsive, metadata, edge cases, a11y)
- [ ] Phase 7 — Deploy to Coolify

## What Phase 1 built

All under `frontend/`.

**Registry and app chrome**
- `lib/tools.ts` — the 10-tool registry plus `getTool` / `getToolBySlug` / `relatedTools` /
  `toolMetadata` and the per-accent Tailwind classes. Fields are the planned ones plus
  `runsIn` (`browser | backend | hybrid`), which is what gates the 50 MB cap.
- `lib/constants.ts` (`APP_NAME`, tagline, `MAX_UPLOAD_BYTES`), `lib/format.ts`,
  `lib/download.ts`.
- `components/layout/` — `site-header` (brand, three quick links, "All tools" dropdown built
  from the registry, theme toggle), `site-footer`, `brand`.
- `components/theme-provider` + `theme-toggle` (next-themes, class strategy).
- Route groups: `app/(site)/` has the footer, `app/(tools)/` does not, so a tool workspace
  fills the viewport under the 64px header.

**Landing page** (`app/(site)/page.tsx`) — hero, the 10 `ToolCard`s driven by the registry
(each card says where it runs), and a "Built so your documents stay yours" section.

**Tool shell** (`components/tool/`)
- `tool-shell.tsx` — owns the state machine and the two-column layout. Status is derived,
  not stored: `phase` is `idle | processing | done | error`, and `idle` renders the dropzone
  or the canvas depending on whether there are files.
- `use-tool-files.ts` — the `{ id, file, name, size, pageCount, thumbnail, rotation, error }`
  list, validation, background page-count/thumbnail loading, reorder/sort/rotate/remove.
- `use-tool-pages.ts` — page-level state for the PageGrid tools, merging user edits
  (reorder, rotate, delete) with the current file list.
- `file-dropzone`, `file-grid` / `file-card`, `page-grid` / `page-card`, `thumbnail`,
  `sortable-grid`, `add-files-button`, `sort-button`, `options-sidebar`, `processing-view`,
  `result-view`, `encrypted-notice`, `tool-shell-context`.
- `tool-page.tsx` / `tool-workspace.tsx` — the `next/dynamic` + `{ ssr: false }` boundary and
  the placeholder processing every stub route currently uses.

**Browser PDF layer** (`lib/pdf/`) — `pdfjs.ts` (worker wiring), `load.ts` (File → pdf.js
proxy or pdf-lib document, `PdfLoadError` with kind `encrypted | invalid | too-large`,
per-File document cache and release), `thumbnails.ts` (page → JPEG data URL, cached per
file + page + rotation + size).

## Decisions made in Phase 1

- **Accent is a single `--brand` token** in `app/globals.css`: a deep teal,
  `oklch(0.48 0.1 200)` light / `oklch(0.74 0.11 200)` dark, deliberately not iLovePDF red.
  `--primary` and `--ring` both point at it, so every shadcn component inherits it, and
  `--color-brand` exposes `bg-brand` / `text-brand`. Changing those two lines re-themes the
  whole app.
- **Tool cards are colour-coded by category, not per tool**: teal for the page-editing tools,
  indigo for Compress, amber for the converters, rose for the password tools. Keeps the grid
  scannable without turning it into a paint chart.
- **Rotation is a CSS transform on the thumbnail**, never a re-render. A quarter turn also
  applies `scale(0.75)` (the thumbnail frame's aspect ratio) or the preview gets clipped.
- **Single-file tools replace rather than append.** Dropping a second file on Split swaps it.
- **`lib/format.ts` regex** uses `/\.[a-z0-9]+$/i`; do not "fix" it to a character class with
  an escaped backslash, bash heredocs mangle that.
- **pdf-lib cannot be trusted to report encryption.** With the AES-256 file qpdf produces it
  throws a plain parse error, not `EncryptedPDFError`, so `load.ts` also scans the bytes for
  an `/Encrypt` entry before calling a file corrupt. pdf.js does raise `PasswordException`
  correctly, and it is what the file list probes with first.
- `@dnd-kit/modifiers` is **not** installed, so `SortableGrid` has no `restrictToParentElement`.
  Add the package if a future phase needs it (remember the Linux lockfile rule).
- Deleted the unused create-next-app SVGs and `app/page.tsx` (moved to `app/(site)/page.tsx`).
- `public/pdf.worker.min.mjs` is now in the eslint ignore list; it was contributing ~1570
  warnings and 6 errors to `npm run lint`.

## Phase 1 verification results

`npm run lint` and `npm run build` are both clean (12 static routes). The rest was driven
through a real headless Chrome (`browse ... --local`) against `npm run dev`:

- Landing page renders 10 cards from the registry, in light and dark, no horizontal scroll.
- Merge: two PDFs dropped in, thumbnails and `3.7 KB · 5 pages` metadata correct; A→Z sort
  reorders and the button flips to Z→A; remove drops the file and the sidebar recounts;
  CTA → processing → "Merge PDF is done" with Download, Start over and three "Continue to"
  links; Start over returns to the select screen.
- Organize: 7 pages from 2 files in one grid with A/B source chips and positions 1-7; rotate
  applies `rotate(90deg) scale(0.75)`; delete renumbers the rest.
- `sample-protected.pdf` → "This PDF is password protected" banner with a working
  `/unlock-pdf` link, the card shows the error, and the CTA is disabled.
- `notes.txt` → toast "notes.txt is not a PDF."
- A 52 MB file on Compress → toast "huge.pdf is over the 50 MB limit." (Browser tools are
  not capped.)
- Compress stub: stage text goes "Uploading" with the bar filling 0→100%, then
  "Running Compress PDF" with the indeterminate bar.
- 390px viewport: sidebar stacks under the grid, `scrollWidth === clientWidth`, nothing
  overflows.

## What Phase 2 built

**PDF operations** (`frontend/lib/pdf/`)
- `save.ts` — `pdfToBlob`, the one place a pdf-lib document becomes a downloadable blob.
- `zip.ts` — `zipBlobs`, used by any tool that produces more than one file. De-duplicates
  entry names (`a.pdf`, `a (2).pdf`) because a zip entry silently overwrites otherwise.
- `merge.ts` — `mergePdfs(files, onProgress)`, `copyPages` in list order.
- `rotate.ts` — `rotatePdf(file, delta)`, adds the delta to each page's existing `/Rotate`.
  Exports `normalizeAngle`, which rounds to the nearest quarter turn.
- `split.ts` — the whole split model: `parsePageExpression`, `validateRanges`, `fixedRanges`,
  `planSplit` (pure, drives the preview and the error message) and `splitPdf` (does the work).

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `merge/` — `merge-workspace` + `merge-options` (numbered order list mirroring the grid).
- `rotate/` — `rotate-workspace`, `rotate-options` (Left/Right for all, per-file degree
  readout, "Reset all"), `rotate-file-action` (the per-card hover button).
- `split/` — `split-workspace`, `split-state` (panel state ⇄ `SplitInput`), `split-options`
  (Range | Pages tabs), `split-preview` (one card per output document, first…last page).

**Shell changes**
- `tool-page.tsx` is now the dispatcher: one `next/dynamic` + `{ ssr: false }` component per
  tool, so each route only downloads its own logic. Tools with no entry fall through to the
  Phase 1 placeholder.
- `tool-shell.tsx`'s `canSubmit` now also accepts a predicate over the readable files.
- `components/tool/page-thumbnail.tsx` — read-only, lazily rendered single-page preview.

## Decisions made in Phase 2

- **`canSubmit` became `boolean | ((files: ToolFile[]) => boolean)`.** The file list lives
  inside `ToolShell` but the CTA gate depends on it (Merge needs two files, Split validates
  its ranges against the real page count), and a predicate was much less invasive than
  lifting the file list out of the shell.
- **`planSplit` is pure and separate from `splitPdf`.** The sidebar's error text, the CTA
  gate and the canvas preview all call it, so they cannot disagree about what the current
  options mean.
- **Empty range bounds mean "the natural end"** — blank From is page 1, blank To is the last
  page, and the input placeholders show the value that will be used. Without this, a
  freshly-added range greets the user with a validation error before they have typed.
- **Split output naming**: `<base>-1-3.pdf` for a range, `<base>-page-5.pdf` for a single
  page, `<base>-split.pdf` when merged, `<base>-split.zip` for the archive.
- **ZIPs use DEFLATE level 1**, not the default 6 or STORE. PDF image data will not shrink,
  but pdf-lib's object streams do, and level 1 gets most of that without seconds of
  main-thread time.
- **Rotate includes unrotated files in the ZIP.** Asking for a set back and receiving only
  part of it is worse than a few bytes of redundancy.
- **Rotate's CTA is gated on at least one non-zero rotation**, so running it can never hand
  back the input unchanged.
- **`pdfToBlob` asserts `Uint8Array<ArrayBuffer>`.** TS 5.9 rejects pdf-lib's
  `Uint8Array<ArrayBufferLike>` as a `BlobPart` because the union admits `SharedArrayBuffer`;
  it never is one here, and asserting beats copying a file that can run to 50 MB.
- Split's panel state deliberately survives "Start over" — re-splitting several documents the
  same way is the common case, and the ranges are re-validated against the new page count.

## Phase 2 verification results

`npm run lint` and `npm run build` are clean (12 static routes). The tools were driven
through a real headless Chrome (`browse ... --local`) against `npm run dev`, and every
output blob was captured (by hooking `URL.createObjectURL`) and read back in Node with
pdf.js, so these are assertions about the actual bytes, not about the screen:

- **Merge** `sample-text.pdf` + `sample-scanned.pdf`, sorted A→Z (which swaps them) →
  7 pages: p1-p2 have no text (the scanned file), p3-p7 are "Page 1 of 5" … "Page 5 of 5"
  in order. Sort button flipped to Z→A.
- **Merge guard**: adding `sample-protected.pdf` shows the Phase 1 encrypted banner with the
  Unlock link, marks the card, and the CTA goes disabled — one readable file is not two.
- **Rotate**, one file: Right ×2 → sidebar reads 180°, thumbnail `rotate(180deg)`, CTA and
  "Reset all" enabled; Reset all → 0°, no transform, CTA disabled again.
- **Rotate**, two files with per-card buttons (text 180°, scanned 90°) → ZIP of
  `sample-text-rotated.pdf` (5 pages, all `rotate=180`, text intact) and
  `sample-scanned-rotated.pdf` (2 pages, all `rotate=90`).
- **Split, custom ranges** 1-2 and 4-5 → ZIP of `sample-text-1-2.pdf` (pages 1,2) and
  `sample-text-4-5.pdf` (pages 4,5); page 3 correctly absent.
- **Split, fixed every 2** on 5 pages → 3 PDFs: `1-2`, `3-4`, `page-5`.
- **Split, pages `1,3-5` + merge** → a single 4-page PDF containing pages 1, 3, 4, 5 in order.
- **Split validation** (each disables the CTA and shows the message in the sidebar, and the
  canvas falls back to a placeholder): `9` → "This PDF has 5 pages, so page 9 does not
  exist."; `abc` → "\"abc\" is not a page number or a range like 3-5."; `5-2` → "Range 5-2
  ends before it starts."; `0` → "Page numbers start at 1."; empty → "Enter the pages you
  want, for example 1,3-5."
- 390px viewport on Split: preview card, tabs and radio cards all stack,
  `scrollWidth === clientWidth`. Checked in both light and dark.

## Test fixtures

`frontend/test-fixtures/` is committed and shared by phases 2-6:

| File | What it is |
|---|---|
| `sample-text.pdf` | 5 pages, real selectable text, 3.7 KB |
| `sample-scanned.pdf` | 2 pages, image only, zero text items (the OCR fixture) |
| `sample-protected.pdf` | `sample-text.pdf` encrypted AES-256, password `hunter2` |

`node scripts/make-test-fixtures.mjs` regenerates the first two. The third needs qpdf from
the backend image; the script prints the command.

## Open questions / risks to watch

- The shadcn `Progress` component does not emit `aria-valuenow`, so upload progress is only
  announced through the `aria-live` stage text. Worth revisiting in Phase 6 (a11y).
- `starlette` warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`.
  Harmless now; revisit if the backend test suite grows in Phase 4.
- Traefik default request body limit vs. the 50 MB upload cap — still flagged for Phase 7.

## Notes for the next session

- **The pattern to copy for Phase 3** is `components/tools/merge|rotate|split/`: a
  `<tool>-workspace.tsx` holding whatever state `process` needs and rendering `<ToolShell>`,
  a `<tool>-options.tsx` rendered inside the shell that reads the file list with
  `useToolShell()`, and pure logic in `lib/pdf/<tool>.ts` that the panel and the process
  callback share. Register the new workspace in `components/tool/tool-page.tsx`'s
  `WORKSPACES` map and it takes over from the placeholder.
- `components/tool/tool-workspace.tsx` is the placeholder and should keep shrinking.
  `PAGE_LEVEL_TOOLS` there now points only Organize and Page numbers at the `PageGrid`;
  both get real workspaces in Phase 3, after which the file can go.
- `components/tool/page-thumbnail.tsx` (Phase 2) is the non-draggable page preview — reuse it
  anywhere Phase 3 needs to show a page without the `PageCard` controls.
- **Bash heredocs really do mangle backslashes** in this environment, as the `lib/format.ts`
  note says: a `/\\/g` written into a heredoc arrives as `/\/g`. Write `.ts`/`.mjs` files with
  the editor tools, not `cat > file <<EOF`.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker,
  never `uv run` directly on host (`uv run pytest` is fine; it doesn't touch the binaries).
- Remember the hydration rule: every tool workspace must stay behind
  `next/dynamic` + `{ ssr: false }` (`components/tool/tool-page.tsx` is that boundary).
