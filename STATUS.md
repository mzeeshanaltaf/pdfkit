# Status

Last updated: 2026-09-18

## Current phase

**Phase 1 — Shared UI shell** — ✅ complete. Next up: **Phase 2 — Browser tools batch 1
(Merge, Rotate, Split)**.

See [`docs/phases/phase-2-browser-tools-1.md`](docs/phases/phase-2-browser-tools-1.md) for
the task list.

## Phase checklist

- [x] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [x] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [ ] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
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

- Phase 2 tools are thin: keep `app/(tools)/<slug>/page.tsx` as is and give each tool its own
  workspace component that calls `<ToolShell tool={...} process={...} options={...} />`. The
  options panel should live inside the shell and read the file list with `useToolShell()`;
  state the `process` callback needs (a password, a rotation) belongs in the workspace above
  the shell, which also passes `canSubmit`.
- `components/tool/tool-workspace.tsx` is the placeholder and should shrink as real tools
  replace it. `PAGE_LEVEL_TOOLS` there is what currently points Organize/Split/Page numbers
  at the `PageGrid`.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker,
  never `uv run` directly on host (`uv run pytest` is fine; it doesn't touch the binaries).
- Remember the hydration rule: every tool workspace must stay behind
  `next/dynamic` + `{ ssr: false }` (`components/tool/tool-page.tsx` is that boundary).
