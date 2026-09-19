# Status

Last updated: 2026-09-19 (Phase 6 + SEO pass + Contact/Privacy pages)

## Current phase

**Phase 6 — Polish** — ✅ complete. Responsive, metadata, icons, empty and error states,
cross-tool consistency and accessibility all went through the full verification matrix, and
the three defects it turned up are fixed. **The app is deploy-ready.**

An **SEO pass** and then a **Contact + Privacy** addition ran after Phase 6 (see below).
Still deploy-ready.

Next up: **Phase 7 — Deploy to Coolify**. See [`docs/phases/phase-7-*.md`](docs/phases/).

## Contact & Privacy pages (2026-09-19)

Built with the `nextjs-contact-form` skill. Two new routes, both in the `(site)` group so
they inherit the footer.

**`/contact`** — Name + Email + Message, posting to `app/api/contact/route.ts`, which
forwards to an n8n webhook with an `x-api-key` header.

- **Progressive enhancement is load-bearing, don't simplify it.** The `<form>` keeps a real
  `action="/api/contact" method="post"` *and* an `onSubmit` fetch. A `"use client"` form
  inside a server component can render correct HTML and still fail to hydrate silently —
  removing the native path turns that into dead UI with no error. The route therefore parses
  both JSON and url-encoded bodies, and answers native posts with a **303** (not 307) so the
  browser re-fetches with GET instead of replaying the POST.
- **Honeypot** is named `hp_field` on purpose. A semantic name (`company`, `phone`, …) would
  be filled by browser/Google autofill and flag real people as bots. Tripping it returns
  success and sends nothing, so bots get no signal to adapt.
- **Rate limit**: `lib/rate-limit.ts`, Upstash sliding window, 5 per 10 min per IP, prefix
  `pdfkit:contact`. It **fails open** when the Upstash vars are absent — a misconfigured env
  must never hard-break the form. The limit check runs *before* the webhook-config check,
  which is also how it can be tested without sending mail.
- `components/ui/textarea.tsx` was added (shadcn had not installed one); the form otherwise
  uses the project's `Input`, `Label`, `Button`.

**`/privacy`** — Privacy policy. The "runs in your browser" and "uses the server" tool lists
are derived from `TOOLS[].runsIn`, so they cannot drift from the registry.

**Wiring** — Contact is in the header (hidden below `sm`, so it is also in the "All tools"
dropdown behind a separator) and, with Privacy, in a new secondary column in the footer. The
footer gained the "Developed with 💖 by [Zeeshan Altaf](https://zeeshanai.cloud)" credit.
Both routes are in `sitemap.ts`; `robots.ts` now disallows `/api/`.

**Env** — four new server-only vars, none `NEXT_PUBLIC_` (they would leak into the client
bundle): `N8N_CONTACT_WEBHOOK_URL`, `N8N_API_KEY`, `UPSTASH_REDIS_REST_URL`,
`UPSTASH_REDIS_REST_TOKEN`. They live in `frontend/.env.local` (Next reads from the app dir,
not the repo root) and are documented in both `.env.example` files. They are **runtime** env,
read per-request in the route handler — passed through `docker-compose.yml`'s frontend
`environment:` block, not as build args.

**Verified against `next start`** — honeypot returns 200 and sends nothing; missing fields
400; bad email 400; native url-encoded post 303 → `/contact?error=email`; rate limiter
allows 5 then 429s on the 6th for a fixed IP; Upstash `/ping` → PONG; one real submission
returned `{"success":true}` from the live n8n webhook. All three of `/`, `/contact`,
`/privacy` render exactly one `h1`, and the header/footer links resolve on tool pages too.
`next build`, `tsc --noEmit` and `eslint` all clean.


## SEO pass (2026-09-19)

Audited with the `seo-audit` skill against the real built output (`next build` + `next start`
+ curl), not against source.

**The finding that mattered:** every tool route served **13 words of body text and no heading
at all**. `ToolPage` is `dynamic(..., { ssr: false })`, so the `h1` and description existed
only after hydration — the ten pages that should rank for "merge pdf", "compress pdf" and so
on were effectively blank, with just 4 crawlable internal links each. The homepage was fine
throughout (288 words, clean hierarchy, all 10 tool links).

**What changed**

- `lib/seo/tool-content.ts` — new. Per-tool search copy: `title`, `h1`, `howTo`, `intro`,
  `steps`, `faqs`. Typed `Record<ToolId, ToolSeo>`, so a new tool will not compile without one.
- `components/seo/tool-seo-section.tsx` — server-rendered section below each workspace,
  carrying the page's single `h1`, the step list, the FAQs and links to all nine other tools.
- `components/seo/json-ld.tsx` — `WebSite` + `WebApplication` on the homepage;
  `BreadcrumbList` + `WebApplication` + `FAQPage` per tool. Rendered server-side, so it is in
  the HTML. Deliberately no `HowTo` (Google retired those rich results in 2023).
- `app/robots.ts`, `app/sitemap.ts`, `app/manifest.ts` — new, all generated from the registry.
- `app/llms.txt/route.ts` — new, `force-static`. Tool list, privacy model and every FAQ, also
  generated from the registry so it cannot drift.
- Metadata titles now come from `TOOL_SEO[id].title` ("Merge PDF Files Online, Free and
  Private" rather than "Merge PDF"), using ~47 of the ~60 characters a SERP shows.
- Workspace headings demoted `h1` → `h2` (`file-dropzone`, `options-sidebar`, `result-view`,
  `tool-shell` error state) so the one `h1` per page is the server-rendered one.
- Footer added to `app/(tools)/layout.tsx`; `ToolPage` gained a `min-h-[calc(100svh-4rem)]`
  floor so the workspace still owns the first viewport.
- Protect's registry description lengthened (66 chars was under the ~70 floor); OG image
  bottom line now opens with a call to action.

**Verified after the change** — all 11 routes: title 45-52 chars, description 73-125, exactly
one `h1`, 288-352 body words, 11 internal links, exactly one JSON-LD block, and every
canonical matches its sitemap entry (the homepage is `SITE_URL` with **no** trailing slash,
which is what Next resolves `canonical: "/"` to). `next build` and `eslint` both clean.

**Open item for Phase 7:** `SITE_URL` falls back to `http://localhost:3000`. Coolify must set
`NEXT_PUBLIC_SITE_URL` **at build time** — it is inlined, not read at runtime. If it is
missing, every canonical, OG URL, sitemap entry and llms.txt link ships pointing at localhost.

## Tools live so far

| Tool | Route | State |
|---|---|---|
| Merge PDF | `/merge-pdf` | ✅ real, browser-side |
| Rotate PDF | `/rotate-pdf` | ✅ real, browser-side |
| Split PDF | `/split-pdf` | ✅ real, browser-side |
| Organize PDF | `/organize-pdf` | ✅ real, browser-side |
| Page numbers | `/add-page-numbers` | ✅ real, browser-side |
| PDF to JPG | `/pdf-to-jpg` | ✅ both modes — pages in the browser, extract-images on the backend |
| Compress PDF | `/compress-pdf` | ✅ real, `POST /compress` |
| Protect PDF | `/protect-pdf` | ✅ real, `POST /protect` |
| Unlock PDF | `/unlock-pdf` | ✅ real, `POST /unlock`, one request per file |
| OCR PDF | `/ocr-pdf` | ✅ real, `POST /ocr` + `GET /ocr/languages` |

## Phase checklist

- [x] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [x] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [x] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
- [x] Phase 3 — Browser tools batch 2 (PDF→JPG page mode, Organize, Page Numbers)
- [x] Phase 4 — Backend services (Compress, Protect, Unlock, OCR, Extract images) + tests
- [x] Phase 5 — Wire backend tools into UI — **feature-complete**
- [x] Phase 6 — Polish (responsive, metadata, edge cases, a11y) — **deploy-ready**
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
  (reorder, rotate, delete) with the current file list. **Deleted in Phase 3**; Organize owns
  that model now, in `components/tools/organize/organize-state.ts`.
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

## What Phase 3 built

**PDF operations** (`frontend/lib/pdf/`)
- `pdfToJpg.ts` — `pdfToJpg(sources, { quality, onProgress, signal })`. Renders each page
  with pdf.js (no explicit `rotation`, so the page's own `/Rotate` is honoured), fills the
  canvas white first (JPEG has no alpha), and encodes with `canvas.toBlob`. `JPG_QUALITIES`
  is the single source of the two presets — Normal scale 2 / quality 0.85 / ≈144 dpi, High
  scale 3 / 0.92 / ≈216 dpi — and the panel reads its labels and dpi from it.
- `organize.ts` — `organizePdf(items, sources, onProgress)`, where an item is
  `{ fileId, pageNumber, rotation }` and `fileId: null` means an inserted blank page. Opens
  each source once and copies all of its wanted pages in a single `copyPages` call.
- `pageNumbers.ts` — `planPageNumbers` (pure, throws `PageNumberError`) and
  `addPageNumbers(file, options, onProgress)`. Covers mode single/facing, the 9-cell
  position, three margins, first number, from/to page, template, font family, size,
  bold/italic (as separate standard faces), underline (a drawn line) and hex colour.

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `pdf-to-jpg/` — `pdf-to-jpg-workspace` + `pdf-to-jpg-options` (mode cards with the live
  "N JPGs will be created" count, quality radios). Uses the default file grid as its canvas.
- `organize/` — `organize-workspace`, `organize-state` (the pure page-list model),
  `organize-canvas` (the combined `PageGrid`), `organize-options` (file list with colour
  chips and surviving page counts, sort, add-blank, reset).
- `page-numbers/` — `page-numbers-workspace`, `page-numbers-state` (panel state ⇄
  `PageNumberOptions`, plus `planFromState` and `previewFile`), `page-numbers-options` (the
  full panel) and `page-numbers-preview` (thumbnails with the red position dot).

**Shell changes**
- `components/tool/source-chip.tsx` — `SourceChip` / `sourceLetter` / `sourceChipClass`: the
  A, B, C… letter and its colour, assigned by position in the file list.
- `ToolPage.fileId` is now `string | null`, `null` meaning an inserted blank page, and
  `PageCard` / `PageGrid` render that as a white sheet labelled "Blank". `PageCard` also
  gained `onInsertAfter` and takes a `sourceIndex` instead of a plain letter.
- `components/tool/use-tool-pages.ts` was **deleted**; Organize owns that model now (see
  the decisions below).
- `tool-workspace.tsx` lost `PAGE_LEVEL_TOOLS` / `PageCanvas` — no placeholder tool needs a
  page grid any more. The four remaining stubs are all file-grid, backend tools.

## Decisions made in Phase 3

- **Organize's page list lives in the workspace, not in the shell**, as a plain value with
  pure operations (`movePage`, `rotatePage`, `deletePage`, `insertBlankAfter`, `sortPages`).
  `process` has to turn that list into a document, and `ToolShell` only hands `process` the
  file list, so the Split pattern — state outside, pure derivation — was the only way for
  the canvas, the sidebar, the CTA gate and the run to agree. This is why
  `use-tool-pages.ts` went: its state was inside the shell where `process` cannot see it,
  and its model had no way to express a blank page.
- **`syncOrganize(state, files)` is pure and idempotent**, keyed on a signature of the file
  list. Every consumer calls it and every edit starts from its result, so no effect is
  needed to reconcile the grid after a file is added or removed, and there is no frame where
  the grid and the output would disagree. Emptying the workspace resets it, so a leftover
  blank page cannot outlive the document it was inserted into.
- **Deleted page ids are remembered, blank ids are not.** A deleted page must not come back
  when the next file is added; a blank page only exists in the list, so remembering it would
  just leak an entry per insert-then-delete.
- **A blank page takes the size of the document's first real page**, falling back to A4, so
  inserting one into a Letter document does not produce a stray A4 sheet.
- **Page numbers lays out in "visual" space and converts to user space at the end.**
  A viewer turns a page clockwise by its `/Rotate` before showing it, so for a sideways page
  the corner the user points at is not the corner pdf-lib draws in. `toUserSpace` does that
  mapping and the text is drawn with `rotate: degrees(rotation)` to cancel the page's own
  turn — which is what makes a number land bottom-right and upright on a `/Rotate 270` page.
- **`{N}` is the last number stamped, not the document's page count.** With the defaults they
  are the same; once numbering starts partway through or at a number other than 1,
  "Page 3 of 6" should count the numbers rather than the paper.
- **The page range is validated against the previewed file but clamped per file at run time.**
  The tool takes several files and they need not be the same length: a range that runs off
  the end of a shorter document numbers what it can, and one starting past the end leaves
  that document alone. `planPageNumbers` stays strict for the UI; `addPageNumbers` clamps.
- **Standard-font text is folded to WinAnsi before drawing.** pdf-lib throws rather than
  dropping characters it cannot encode, and curly quotes and dashes are exactly what someone
  pastes into a custom template, so those are mapped to ASCII and the rest dropped.
- **PDF→JPG caps the rendered edge at 8000px.** Browsers silently return blank bitmaps past
  their canvas limit, so a poster-sized page at High quality loses a little resolution rather
  than coming out black. Each canvas is also zeroed after encoding so a long document does
  not hold one full-size bitmap per page until the next GC.
- **JPG filenames are zero-padded** (`page-01`, not `page-1`) so the extracted folder sorts
  in page order.
- **The blank-page card is white in both themes.** It stands for white paper, and a dark card
  beside the real thumbnails reads as a failed render.

## Phase 3 verification results

`npm run lint`, `npx tsc --noEmit` and `npm run build` are clean (12 static routes). The
tools were driven through a real headless Chrome (`browse … --local`) against `npm run dev`,
and every output blob was captured (by hooking `URL.createObjectURL`) and read back in Node
with pdf-lib and pdf.js — so these are assertions about the actual bytes, not the screen.

- **PDF→JPG, quality**: `sample-text.pdf` at Normal → ZIP of 5 JPEGs, each 840×1190;
  at High → 1260×1785, exactly 1.5× (284 KB vs 737 KB for the ZIP). Entries are
  `sample-text-page-1.jpg` … `-page-5.jpg`.
- **PDF→JPG, single page**: a one-page PDF → no ZIP, a single `image/jpeg` blob (19 KB) and
  the button reads "Download" rather than a count. Five pages → "Download 5 JPG images".
- **PDF→JPG panel**: the count is live from the loaded page total ("5 JPGs will be created,
  one per page"), and "Extract images" renders with a "Coming soon" badge and is disabled.
- **Organize, combined grid**: `sample-text.pdf` + `sample-scanned.pdf` → 7 cards, chipped
  A×5 and B×2. A real pointer drag (`browse mouse drag`) moved card 7 (B p2) to the front,
  then rotate on position 1, delete on position 3, and insert-blank after position 1 gave
  `[B2 rotated 90°, blank, A1, A3, A4, A5, B1]`, with the sidebar reading "7 pages, 1 of
  them blank, 1 rotated".
- **Organize, output**: the resulting PDF is exactly that list — p1 rotate=90 with one image
  (the scanned page), p2 with **zero draw operations** (genuinely blank) at 420×595 like its
  neighbours, p3/p4/p5/p6 carrying "Page 1 of 5", "Page 3 of 5", "Page 4 of 5", "Page 5 of 5"
  (page 2 correctly absent) and p7 the other scanned page.
- **Page numbers, facing**: bottom-right, "Page {n} of {N}", facing on, from page 2 →
  page 1 unstamped; pages 2 and 4 stamped bottom-**left**, pages 3 and 5 bottom-**right**,
  with texts "Page 1 of 4" … "Page 4 of 4" ({N} = 4, the last number stamped). The preview
  dots matched: `left:9%` on even pages, `left:91%` on odd, none on page 1.
- **Page numbers, rotated pages**: a fixture with `/Rotate` 0, 90, 180 and 270 → all four
  numbers land bottom-right **in the displayed page** (including the 595×420 landscape
  views) and all four read upright once the text direction is pushed through the viewport
  transform.
- **Page numbers, style**: Times + bold + italic + underline + 20 pt → the output embeds
  `/Times-BoldItalic`, pdf.js reports the stamp as serif at height 20, one stroked path per
  page for the underline, and the fill colour is the chosen `#222222`.
- **Page numbers, several files**: `sample-text.pdf` + `sample-scanned.pdf` with to-page 5 →
  ZIP of `sample-text-numbered.pdf` (5 stamps) and `sample-scanned-numbered.pdf`
  (2 stamps, text "Page 1 of 2"), i.e. the range clamped to the shorter document and `{N}`
  recomputed for it.
- **Page numbers, validation**: from page 9 on a 5-page file → "This PDF has 5 pages, so that
  range does not exist." in an `alert`, and the CTA goes disabled.
- 390px viewport on all three tools: `scrollWidth === clientWidth`, nothing overflows.

## What Phase 4 built

All under `backend/`. `backend/README.md` now carries the full endpoint and error-code
table — that is the reference Phase 5 should code the client against.

**Shared infrastructure**
- `app/config.py` — `MAX_UPLOAD_MB` 50, `MAX_FILES_PER_REQUEST` 20, `MAX_CONCURRENT_JOBS` 2,
  `MAX_OCR_LANGUAGES` 3, `QUEUE_TIMEOUT_SECONDS`, `CORS_ORIGINS`, and a per-operation
  `TIMEOUTS` map read through `timeout_for()` (OCR gets 600 s, qpdf 60 s).
- `app/deps.py` — `save_uploads()` streams each upload to a per-request temp directory in
  1 MB chunks, rejecting >50 MB (413), non-`%PDF-` (415) and empty (400) as it goes.
  `display_name` / `sanitise_filename` are the two name cleaners; `UploadBatch` owns the
  temp directory and `upload_batch()` is the context manager that guarantees cleanup on
  failure.
- `app/services/runner.py` — the only place a subprocess is spawned. Global
  `Semaphore(MAX_CONCURRENT_JOBS)`, per-operation `asyncio.wait_for`, an explicit
  `process.kill()` on timeout, and `sanitise()` to strip absolute paths out of any tool
  output before it reaches a client.
- `app/services/responses.py` — `file_response()`: one output as itself, several as a
  DEFLATE-1 zip, `Content-Disposition` from the original upload name, and a
  `BackgroundTask` that deletes the temp directory after the body is sent.
- `app/services/errors.py` — `mentions_password()` (reading tool stderr) and
  `ensure_readable()` (the pypdf pre-check).
- `app/services/passwords.py` — `validate_password`, and the two 0600 secret-file writers
  that keep passwords out of argv.

**Services and routers** — `compress` (Ghostscript), `protect` / `unlock` (qpdf),
`ocr` (OCRmyPDF + the Tesseract language list), `images` (pdfimages + Pillow), each with a
thin router in `app/routers/`.

**Docker** — the Dockerfile is now multi-stage: `base` (system tools + prod deps) →
`test` (dev deps + `tests/`) and `runtime` (the default target, the only one that ships).
`docker-compose.yml` gained a `backend-tests` service behind the `test` profile.

## Decisions made in Phase 4

- **Ghostscript 10 exits `0` on a PDF it cannot decrypt**, writing a plausible-looking but
  empty output. Left alone, compressing a locked file would have returned a blank document
  with a 200. So `ensure_readable()` pre-checks every input with pypdf and returns
  `422 password_required` before any native tool runs. It deliberately allows an
  owner-password-only file through (encrypted, but opens with the empty password) because
  every tool here reads one fine — there is a test for each half of that.
- **pypdf pre-read failures are swallowed, not raised.** pypdf is far stricter than qpdf and
  Ghostscript and throws a wide, undocumented spread of exceptions on damaged files.
  Anything other than a clean "yes, encrypted" means we learned nothing, so the real tool
  gets its turn rather than the request being refused.
- **Protect uses `qpdf @argfile`, not `--password-file`.** Debian bookworm ships qpdf 11.3,
  where the encryption passwords are *positional* — `--user-password=` / `--owner-password=`
  only arrived in 11.7. An argument file is the only way to keep them out of `ps` on this
  version. Unlock does use `--password-file=`, which 11.3 has. Verified empirically in the
  container before either was written.
- **A password containing `\r`, `\n` or `\0` is rejected with 400.** The argument file is
  line-delimited, so a newline in a password is argument injection into qpdf. Escaping was
  not worth it — no viewer's password box can produce one.
- **`ToolResult` rather than exceptions for non-zero exits.** Unlock has to tell
  "wrong password" from "broken file", which means reading stderr itself, so `run()` takes
  `check=False` and hands the result back. With `check=True` (everything else) a non-zero
  exit becomes a 500 carrying a sanitised excerpt.
- **The temp directory is freed by a `BackgroundTask`, never a `yield` dependency.** Since
  FastAPI 0.106 the exit half of a `yield` dependency runs *before* the response body is
  sent, which would delete the file mid-stream. This is written at the top of `deps.py` so
  nobody "simplifies" it back.
- **Compress falls back to the original bytes when pdfwrite does not help.** An already-lean
  or vector-heavy PDF regularly comes back larger; returning a worse file for the same wait
  is not a result. `X-Original-Size` / `X-Result-Size` are then equal, and both headers are
  in the CORS `expose_headers` list so the UI can actually read them.
- **`/images/extract` always returns a zip**, even for one image, as the phase doc
  specifies — see the open question below, because the browser-side PDF→JPG mode does not.
- **Extraction drops images under 16 px** (spacers, rules, tracking pixels) and stops at 500
  per file.
- **Absent and empty `password` on `/protect` both give `400 password_missing`.** The field
  is declared optional purely so that FastAPI's 422 validation envelope never appears for
  one of them — the UI should only ever have to read `detail`.
- **`osd` and `equ` are filtered out of `/ocr/languages`**: they are Tesseract's
  script-detection and maths models, not languages. The list is cached behind an
  `asyncio.Lock`; it only changes on redeploy.
- **OCR uses `--skip-text`**, so a born-digital PDF passes through with its text intact
  rather than gaining a second, worse layer. `TMPDIR` is pointed at the request's own
  workspace so OCRmyPDF's scratch files die with the batch.
- **The tmpfs mount has to name uid/gid 1001.** A tmpfs masks whatever ownership the image
  gave the path, so `/tmp/pdfkit` arrived root-owned and every upload failed with
  `PermissionError` even though the Dockerfile chowns it. `docker-compose.yml` now mounts it
  `uid=1001,gid=1001,mode=0700` and the Dockerfile pins the gid so the two cannot drift.
  **Phase 7 must carry this into the Coolify compose too.** `_scratch_root()` also falls back
  to the platform temp dir with a warning rather than 500-ing, so a misconfigured deploy
  degrades instead of breaking.
- **The suite lives in its own build target.** Shipping pytest and the tests in the runtime
  image to satisfy the phase doc's `docker compose run --rm backend pytest` was not worth it;
  the command is `docker compose --profile test run --rm backend-tests` instead.

## Phase 4 verification results

`docker compose --profile test run --rm backend-tests pytest -q` → **53 passed**. Fixtures
are generated at run time (a hand-assembled text PDF, a Pillow/DejaVu image-only PDF, a
gradient photo PDF, and two qpdf-encrypted variants), so no binary test assets are committed.

Three real bugs were found by the first test run and one more by the first curl run; all four
are fixed and each now has a regression test:

1. Ghostscript's silent-success-on-encrypted-input, above.
2. `/protect` with an empty password returned FastAPI's 422 envelope rather than our 400.
3. The 415 message renamed the user's file before quoting it back — "notes.txt.pdf is not a
   PDF file."
4. Zip downloads were named `pdfkit-compressed.zip.zip`, because `sanitise_filename` forces
   `.pdf` and `sanitise_archive_name` then appended `.zip` to the whole thing.

Then, against `docker compose up backend` (the real runtime image, non-root, tmpfs):

- `GET /health` → `{"status":"ok"}`; `GET /ocr/languages` → `[{"code":"eng","name":"English"}]`.
- **Compress** a 318,670-byte photo PDF at `recommended` → 81,615 bytes, `%PDF-`,
  `X-Original-Size: 318670`, `X-Result-Size: 81615`,
  `Content-Disposition: attachment; filename="photo-compressed.pdf"`.
- **Compress no-gain**: `sample-text.pdf` at `extreme` → output **byte-identical** to the
  input, both size headers 3795.
- **Compress two files** → `application/zip`, `pdfkit-compressed.zip`, entries
  `sample-text-compressed.pdf` + `photo-compressed.pdf`.
- **Protect → unlock**: `sample-text.pdf` + password `correct horse` → 4,656-byte encrypted
  PDF; unlocking it with no password → `422 password_required`, with `wrong` →
  `422 wrong_password`, with the right one → `200` and a valid 3,960-byte PDF.
- The committed `sample-protected.pdf` behaves identically (`422` without, `200` with
  `hunter2`).
- **OCR**: `pdftotext` on the input reports 0 non-space characters; after `POST /ocr` it
  reports `INVOICE 1 INVOICE 2`. (Not with `sample-scanned.pdf` — see the open question.)
- **Extract images** from the photo PDF → `photo-images.zip` holding
  `photo-image-001.jpg`, a real 1600×2200 JPEG; `high` (365,752 B) > `normal` (295,003 B).
  A text-only PDF → `422 no_images_found`.
- **Rejections**: `notes.txt` → `415 "notes.txt is not a PDF file."`; a 51 MB file →
  `413 "huge.pdf is over the 50 MB limit."`; `level=maximum` and `languages=eng,klingon` →
  400 with a readable message.
- **No leaks**: after all of the above, `ls -A /tmp/pdfkit` inside the container is empty —
  every request cleaned up after itself.

## Test fixtures

`frontend/test-fixtures/` is committed and shared by phases 2-6:

| File | What it is |
|---|---|
| `sample-text.pdf` | 5 pages, real selectable text, 3.7 KB |
| `sample-scanned.pdf` | 2 pages, a 300 dpi raster of `sample-text.pdf`, zero text items — 274 KB |
| `sample-protected.pdf` | `sample-text.pdf` encrypted AES-256, password `hunter2` |

`node scripts/make-test-fixtures.mjs` now regenerates **all three** in one command. It shells
out to the backend image for the two steps this machine cannot do locally (poppler to
rasterise, qpdf to encrypt), which is no new requirement — the backend only ever runs in
Docker anyway.

**Phase 6 replaced `sample-scanned.pdf`.** The old one drew four black bars, described in its
own generator as "a word-shaped smudge to a person": it had no glyphs, so Tesseract returned
nothing and the OCR row of the matrix could never have passed. It was also 1.4 KB, so
Ghostscript returned it unchanged at every level and Compress could not be measured either.
It is now a real 300 dpi render of the text fixture — genuinely readable to OCR, and with
enough raster data that the three compression levels separate. 300 dpi specifically, because
Compress maps its levels to 72 / 150 / 300 dpi and a 150 dpi source leaves the top two
levels with nothing to downsample.

## Open questions / risks to watch

- The shadcn `Progress` component does not emit `aria-valuenow`, so upload progress is only
  announced through the `aria-live` stage text. Worth revisiting in Phase 6 (a11y).
- `starlette` warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`.
  Still harmless at 53 tests; it is the only warning the suite emits.
- Traefik default request body limit vs. the 50 MB upload cap — still flagged for Phase 7.
- The `X-Original-Size` / `X-Result-Size` headers are only readable cross-origin because they
  are in `expose_headers` in `main.py`. If a reverse proxy strips them in Phase 7, the
  compress UI silently loses its before/after numbers — it degrades to no size line rather
  than to a wrong one, but it is worth checking after the deploy.
- **Resolved in Phase 5 — `sample-scanned.pdf` cannot demonstrate OCR.**
  `make-test-fixtures.mjs` draws stroke-shaped smudges rather than glyphs, so Tesseract
  correctly finds nothing in it. Phase 5 did not change the committed fixture (phases 2-3
  assert against it); it generated a throwaway 600 dpi image-only PDF with real rendered
  lettering in the scratchpad instead, which is also what made the compression levels
  distinguishable. If a committed OCR fixture is ever wanted, `build_scanned_pdf()` in
  `backend/tests/conftest.py` is the shape to copy.
- **Resolved in Phase 5 — `/images/extract` always returns a zip, even for one image**,
  while the browser-side page mode returns a bare JPEG for a single page. Deliberately left
  inconsistent: the page mode's output count is known before the run (one per page, and the
  panel says so), whereas extraction's is not known until poppler has looked. A tool that
  unpredictably hands back either a `.jpg` or a `.zip` is worse than one that always hands
  back a `.zip`, so extraction always zips and the panel says that too.

## Notes for the next session

- **Phase 6 is polish**: responsive sweep, metadata, edge cases and a11y across all 10 tools.
  Everything is functional as of Phase 5, so this is refinement, not wiring.
- **Run both halves while working**: `docker compose up backend` plus `npm run dev`, with
  `NEXT_PUBLIC_API_URL=http://localhost:8000` (already in `frontend/.env.local`). CORS
  allows `localhost:3000` and `127.0.0.1:3000`.
- **Backend commands**, for reference:
  - `docker compose up backend` — the runtime image, port 8000.
  - `docker compose --profile test run --rm backend-tests` — the suite (53 tests).
  - `docker compose --profile test build backend-tests` after changing `app/` or `tests/`.
  - Note the phase doc's `docker compose run --rm backend pytest` does **not** work: the
    runtime image deliberately carries neither pytest nor the tests.
  - `docker cp` cannot read `/tmp/pdfkit` — it is a tmpfs mount. To get a file out of the
    container, `docker compose exec -T backend base64 -w0 //tmp/pdfkit/<file>` and decode it
    on this side (the leading `//` stops Git Bash rewriting the path).
- **When adding a backend endpoint**: service in `app/services/`, thin router in
  `app/routers/`, register it in `app/routers/__init__.py`'s `ROUTERS`. Never call
  `asyncio.create_subprocess_exec` directly — go through `app/services/runner.py`, which owns
  the concurrency limit, the timeout and stderr sanitising.
- **The browser-tool pattern** (`merge|rotate|split`, `pdf-to-jpg|organize|page-numbers`): a
  `<tool>-workspace.tsx` holding whatever state `process` needs and rendering `<ToolShell>`,
  a `<tool>-options.tsx` rendered inside the shell that reads the file list with
  `useToolShell()`, and pure logic in `lib/pdf/<tool>.ts` that the panel and the process
  callback share.
- **The backend-tool pattern** (`compress|protect|ocr`, and PDF→JPG's extract mode): the same
  shape, but `process` is one call to `runBackendTool(context, endpoint, fields, …)` from
  `components/tool/backend-run.ts`, which owns the upload-progress-then-indeterminate
  sequence. Unlock is the one exception — it loops per file through `uploadWithPassword` so
  each file can have its own password.
- **Every tool now has a workspace**, and `WORKSPACES` in `components/tool/tool-page.tsx` is
  a total `Record<ToolId, ComponentType>` — adding a tool to `lib/tools.ts` without a
  workspace is now a type error rather than a silent fallback to a placeholder.
- **Anything a tool's `process` must see has to live outside `ToolShell`**, because the shell
  only passes `process` the file list. Keep it as a plain value plus pure functions and
  derive against `files` in the panel, the canvas, the CTA predicate and the run — Split's
  `planFromState` and Organize's `syncOrganize` are the two worked examples.
- **Error surfacing has two channels now.** Throw an `ApiError` with `recoverable: true` and
  `ToolShell` shows a toast and returns to the file list with everything intact; throw
  anything else and it shows the full-page failure screen. `silent: true` skips the toast
  (used when the user cancels a password prompt). Everything from `lib/api.ts` is already
  classified — see `recoverableStatus`.
- **`eslint` forbids `setState` inside an effect** (`react-hooks/set-state-in-effect`), and
  it is an error, not a warning. Derive with `useMemo` instead — OCR's language filtering is
  the worked example.
- `components/tool/page-thumbnail.tsx` is the non-draggable page preview (Split preview, Page
  numbers preview); `PageGrid` / `PageCard` is the editable one (Organize only).
- **Bash heredocs really do mangle backslashes** in this environment, as the `lib/format.ts`
  note says: a `/\\/g` written into a heredoc arrives as `/\/g`. Write `.ts`/`.mjs` files with
  the editor tools, not `cat > file <<EOF` — including when editing this file, which is how
  this very line was mangled once already.
- **How the tools were verified**, if an output ever needs re-checking: hook
  `URL.createObjectURL` in the page, run the tool, click Download, then read the captured
  blob back as base64 and inspect it in Node with pdf-lib/pdf.js from
  `frontend/node_modules`. That is the only way to assert on the bytes rather than the
  screen. A hook on `XMLHttpRequest.open` / `fetch` is the matching trick for proving that a
  rejected file never left the browser.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker,
  never `uv run` directly on host (`uv run pytest` is fine; it doesn't touch the binaries).
- Remember the hydration rule: every tool workspace must stay behind
  `next/dynamic` + `{ ssr: false }` (`components/tool/tool-page.tsx` is that boundary).

## What Phase 5 built

All under `frontend/`.

**Backend client**
- `lib/api.ts` — the browser's half of the FastAPI service. `uploadAndProcess(endpoint,
  files, fields, { onProgress, signal, fallbackName })` over `XMLHttpRequest`, returning
  `{ blob, filename, headers }`; `ApiError` (status, backend `code`, `recoverable`,
  `silent`); `assertUploadable` for the 50 MB pre-check; `filenameFromDisposition`;
  `uploadWithPassword` for the ask-and-retry protocol; `getJson` for `/ocr/languages`.
- `lib/file-handoff.ts` — the module-level slot that carries a `File` from one tool to
  another across a client-side navigation.
- `components/tool/backend-run.ts` — `runBackendTool`, the shared "upload % then
  indeterminate" progress pattern, plus `numericHeader`.
- `components/tool/password-dialog.tsx` — `usePasswordPrompt()` returning
  `{ requestPassword, dismissPrompt, passwordDialog }`. `lib/api.ts` owns the retry
  protocol; this owns the UI.

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `compress/` — three radio cards (Extreme / Recommended / Less) plus a size summary.
- `protect/` — password + repeat with a shared show/hide toggle, inline mismatch error, and
  `protectReady()` as the single CTA gate.
- `unlock/` — the "just press the button" callout and a per-file lock/unlock list.
- `ocr/` — `use-ocr-languages.ts` (fetches `GET /ocr/languages`, falls back to English with
  a toast) and the max-3 language picker with the accuracy callout.
- `pdf-to-jpg/` — "Extract images" is live; the quality labels and footer text now change
  with the mode, since dpi means nothing when extracting stored bitmaps.

**Shell changes**
- `ToolShell` gained `acceptEncrypted`, `adoptFiles` and `overlay`, and now turns a
  recoverable `ApiError` into a toast plus a step back to the file list rather than the
  full-page failure screen.
- `EncryptedNotice` takes `ToolFile[]` and hands the files to Unlock on click.
- `FileGrid` / `FileCard` / `Thumbnail` gained `allowEncrypted` / `locked`, so on Unlock a
  protected file reads as amber "locked" rather than a red failure.
- `tool-page.tsx`'s `WORKSPACES` is now a total `Record<ToolId, ComponentType>`, and
  `components/tool/tool-workspace.tsx` (the placeholder) was **deleted** — every tool has a
  real workspace.

## Decisions made in Phase 5

- **A recoverable failure is a toast, not the error screen.** A wrong password, a busy or
  unreachable server, or a PDF with no images to extract all leave the workspace exactly as
  it was; replacing the screen with a failure page throws that away for nothing. `ApiError`
  carries `recoverable` (everything except a 5xx that is not 503/504) and `silent` (the user
  cancelled), and `ToolShell` branches on them. The full-page error screen is now reserved
  for genuine server faults.
- **Unlock sends one request per file; every other backend tool sends the batch.** The
  backend takes a single `password` per request, so a batch of differently-locked files
  would fail whole at the first one. Per file, each gets its own prompt, its own retry and
  its own inline error; the outputs are zipped client-side with the existing `zipBlobs`.
- **The first unlock attempt deliberately carries no password.** A file locked with only an
  owner password opens with the empty one, so prompting up front would ask for something the
  user does not have. `password_required` means that attempt failed; `wrong_password` means
  the typed one did — the dialog is told which, which is what lets it show an inline error
  instead of a generic toast.
- **The password dialog stays mounted between attempts**, and its resolver lives in a ref
  rather than in state, because it has to be callable from an event handler without going
  through a React updater. The form is keyed on the *filename*: a rejected password is left
  in the field (usually a typo away from right) but pre-selected, while moving to the next
  file starts empty.
- **`ToolShell.acceptEncrypted` exists because `readableFiles` excluded the very files
  Unlock is for.** It also had to drop encrypted files out of the `stillLoading` check —
  they never get a page count, so the CTA would have stayed disabled for good.
- **The encrypted-PDF banner hands the actual `File` over**, through a module-level slot
  that survives a `next/link` navigation and is emptied on read. A full page load loses it,
  which is correct: the `File` objects are gone by then anyway.
- **Compress's saving is a batch total, not per file.** `ToolResult` carries one blob and
  one size pair, and `X-Original-Size` / `X-Result-Size` are sums over the request — so for
  the single-file case (the common one) it is per-file, and for a batch it is the honest
  total. Per-file numbers would mean one request per file and a different result screen.
- **The progress bar goes indeterminate the moment the upload finishes**, rather than
  sitting at 100%. Once the last byte is on the wire there is no honest percentage for
  Ghostscript's or Tesseract's share of the wait.
- **The OCR language list comes from the server, and an empty selection disables the CTA.**
  Which models exist is a property of the backend image, so hardcoding them here would go
  stale on the next Dockerfile change. An earlier version back-filled the first installed
  language when the selection emptied, which made unchecking the only language look like a
  broken checkbox; it now simply disables the CTA and the panel says why.
- **PDF→JPG's quality labels change with the mode.** "≈144 dpi" is meaningful when a page is
  being rendered and meaningless when a stored bitmap is being re-compressed, so extraction
  shows "smaller files" / "less JPEG loss" instead.

## Phase 5 verification results

`npm run lint`, `npx tsc --noEmit` and `npm run build` are clean (12 static routes). The
tools were driven through a real headless Chrome (`browse … --local`) against `npm run dev`
with `docker compose up backend`, and every output blob was captured (by hooking
`URL.createObjectURL`) and read back in Node — so these are assertions about the bytes the
browser actually downloaded, not about the screen.

Fixture: a generated 2-page, 600 dpi, image-only PDF (928 KB) with legible rendered text and
a photo-like block. `sample-text.pdf` is far too lean for Ghostscript to improve on and too
small to tell the compression levels apart. Not committed — it lives in the scratchpad, and
the committed fixtures are still the ones phases 2-4 use.

- **Compress, all three levels** on the same file: 928 KB → 41.9 KB (95%), → 108 KB (88%),
  → 445 KB (52%) — a strict extreme < recommended < less ordering. Each downloaded blob is
  byte-for-byte the size curl gets from the endpoint, and all three open with pdf-lib at
  2 pages / 408×528. The readout comes from `X-Original-Size` / `X-Result-Size`.
- **Compress, two files** → a ZIP of `rich-scan-compressed.pdf` and
  `report-two-compressed.pdf`, with the result screen showing the batch total.
- **Protect**: the CTA is disabled while the fields are empty, still disabled with an inline
  "The two passwords do not match." on mismatch, and enabled once they match. The file the
  *browser* downloaded reports `R = 6` and `stream/string/file encryption method: AESv3`
  under `qpdf --show-encryption`, is refused by `qpdf --check` with "invalid password", and
  passes `qpdf --password=hunter2 --check`.
- **Unlock, round trip** on that same protected file: the card reads amber "4.5 KB · locked"
  and the CTA is enabled, with no encrypted-PDF banner. A wrong password leaves the dialog
  open with "That password did not open the file. Try again.", `aria-invalid="true"`, no
  toast and no error screen; `hunter2` then succeeds.
- **Unlock, two files with different passwords** (`hunter2` and `secondpass`): prompted one
  at a time, each field starting empty with no stale retry error; result "Download 2 unlocked
  PDFs" → a ZIP of two 5-page PDFs with no `/Encrypt` and page 1 text intact.
- **Unlock, cancelled prompt** → straight back to the file list, no toast, no error screen.
- **Encrypted-guard handoff**: a locked file on Merge shows the banner with the CTA disabled;
  clicking "Unlock this file" lands on `/unlock-pdf` with that file already loaded and the
  CTA ready. A full page reload correctly shows an empty dropzone instead.
- **OCR**: the picker is populated from `GET /ocr/languages` (`English / eng`) with English
  checked; unchecking it disables the CTA and shows "Pick at least one language". The
  image-only fixture goes from **0 characters** of extractable text to **463**, reading
  "THE QUARTERLY REPORT Revenue grew by eleven percent across the northern region…".
- **Progress is real, not a timer**: sampling the processing view every 40 ms during the OCR
  run captured "Uploading your file" with a determinate bar, then "Reading the pages — this
  is the slow part" with the indeterminate one. That flip is driven only by `onProgress(100)`.
- **PDF→JPG, extract images**: the "Coming soon" badge is gone and the mode runs; the ZIP
  holds `rich-scan-image-001.jpg` / `-002.jpg`, both valid JPEGs at the stored **3400×4400**
  — i.e. the embedded originals, not a re-render of the page. A text-only PDF gives the toast
  "There are no embedded images in this PDF to extract." with the workspace left intact.
- **Backend unreachable** — both with the container stopped before the request and killed
  mid-OCR — gives "Could not reach the server. Check it is running and try again." as a
  toast, keeps the files, and leaves the CTA usable. No hang, no crash, no error screen.
- **Client-side pre-checks**: a 52 MB `huge.pdf` → "huge.pdf is over the 50 MB limit.";
  `notes.txt` → "notes.txt is not a PDF." Both stay on the dropzone, and a hook on
  `XMLHttpRequest.open` / `fetch` confirms **zero requests left the browser**. The same
  52 MB file is accepted on Merge (a browser tool, uncapped) and only then fails to parse.
- **390 px viewport** on Compress, Protect, Unlock, OCR and PDF→JPG: no horizontal overflow
  and the sidebar stacked under the canvas in every case. The password dialog sits at
  16 px / 374 px in a 390 px viewport.
- **Browser-tool regression** after the shell changes: Merge still produces the 7-page
  document ("Page 1 of 5" … "Page 5 of 5" then the two scanned pages), and Split still
  produces its 5-page output.

## Open notes for Phase 6 (all addressed)

- ~~`503 server_busy` and `504 processing_timed_out` are mapped and take the same
  recoverable-toast path as the errors above, but were not triggered live.~~ Phase 6 drove
  both (plus a 500 and a refused connection) by intercepting the request in the browser.
- Only `eng` is installed in the backend image, so the OCR picker's max-3 cap and its
  language ordering are not exercised by anything but reading the code.
- Compress, Protect and OCR reject an encrypted input at the backend with
  `422 password_required`, but the client-side encrypted guard means one never reaches them;
  that error therefore has no dedicated UI beyond the generic toast.

## What Phase 6 built

All under `frontend/`.

**Metadata and icons**
- `lib/constants.ts` — `SITE_URL` (from `NEXT_PUBLIC_SITE_URL`, localhost fallback so
  `next build` works before a domain exists) and `BRAND_HEX`, the plain-hex form of
  `--brand` for the two places that cannot read a CSS custom property.
- `app/layout.tsx` — `metadataBase`, site-wide `openGraph` / `twitter`, and a `viewport`
  export with a per-theme `themeColor`.
- `lib/tools.ts` — `toolMetadata` now returns `openGraph` and `twitter` alongside the title,
  description and canonical, all still read from the registry.
- `app/icon.svg` (favicon), `app/favicon.ico` (rasterised from it), `app/apple-icon.png`
  (the same mark, squared off) and `app/opengraph-image.tsx` (a generated 1200×630 card).

**Structure**
- The `main` landmark moved out of `ToolShell` and into the two route-group layouts, so it
  wraps every phase of the state machine rather than only the configure screen.
- `FileDropzone`'s heading is the tool name as an `h1`, matching the sidebar's `h1` in the
  configure phase — every page now has exactly one, and it says the same thing either way.

**Mobile**
- The sidebar CTA is `sticky bottom-0` below `lg`, so it stays in reach at the bottom of a
  long options list instead of sitting under it.

## Defects Phase 6 found and fixed

1. **A 500 from the backend took over the screen.** `recoverableStatus` treated 500 and 502
   as unrecoverable, so a Ghostscript crash or a proxy error threw the whole workspace away
   for a full-page failure screen — exactly the case where the file list is still fine and
   the next step is a retry or a gentler setting. Every answer the server gives is now
   recoverable; the failure page is reserved for errors raised on this side, where the state
   really is in doubt.
2. **Enter on a page-card button also started a keyboard drag.** `PageCard` spread dnd-kit's
   `attributes` on the `<li>` and named no activator, and dnd-kit's keyboard sensor only
   skips a keypress when there *is* an activator to compare against — so Space or Enter on
   "Delete page 3" both deleted the page and began dragging it. `PageCard` now has a grip
   button carrying `setActivatorNodeRef` + `attributes` (as `FileCard` already did), with
   the pointer `listeners` left on the `<li>` so dragging anywhere on a card still works.
   It also removes a button nested inside a `role="button"`.
3. **`sample-scanned.pdf` could not have passed the OCR or Compress rows.** See the test
   fixtures section above.

## Phase 6 verification results

Driven headlessly with Playwright against `next build` + the standalone server on :3000
(the backend's CORS allows :3000 only), with the Dockerised backend up. The harness lives in
the session scratchpad, not the repo — adding Playwright as a project dependency is a stack
decision Phase 6 has no mandate for. **Worth considering for Phase 7**, since it catches
regressions in a deploy far faster than clicking through ten tools.

| Area | Result |
|---|---|
| All 11 pages (10 tools + landing) at 390 px and 1440 px | no horizontal scroll, exactly one `h1`, exactly one `main`, zero console errors or warnings |
| Encrypted guard | banner + `/unlock-pdf` link + disabled CTA on all 9 guarded tools; Unlock accepts the file, shows no banner, marks the card "locked" |
| Non-PDF rejection | clear toast on all 10 tools |
| >50 MB rejection | clear toast on the 5 tools that can post; correctly not applied to browser-only tools |
| Merge | dropped order, sorted A–Z, and drag-reordered all produce the expected page order (checked by which pages carry text, not just page counts) |
| Split | custom range 2–4 → 3 pages; fixed every 2 → 3 documents; pages `"1,3-5"` merged → 4 pages, page 2 absent |
| Rotate | right twice → 180° on every page; "Reset all" → 0° and the CTA closes again; per-file rotate turns only that file |
| Organize | delete + rotate + insert blank across two files → 7 pages with one at 90°; sort restores file order |
| Page numbers | from page 2 → page 1 skipped, the rest numbered 1–4; "Start at 100" → 100…104; facing mode mirrors the stamp (x=381 odd, x=32 even) |
| PDF→JPG | normal 840×1190 vs high 1260×1785; extract images → 2 embedded JPEGs |
| Compress | extreme 64 KB < recommended 210 KB < less 274 KB, all three open |
| OCR | scan goes from 0 text items to ~820 characters per page |
| Protect / Unlock | output refuses to open without the password and opens with it; Unlock strips it; a wrong password re-prompts inline instead of failing the run |
| Backend failures | connection refused, 500, 503 and 504 each show a toast and return to the files — never stuck on "Processing…", never a failure page |
| Corrupt PDF | flagged on its own card, removable, and the other files still run; a corrupt-only workspace disables the CTA |
| Accessibility | every grid and panel control tab-reachable, every focus stop paints a ring, Enter on a page action no longer drags, Space on the grip still does |
| Contrast | zero text nodes below WCAG AA on the landing page and three workspaces, in both light and dark, measured against the real composited background |
| `npm run lint && npm run build` | clean |

## Open notes for Phase 7

- `NEXT_PUBLIC_SITE_URL` must be set at **build** time in Coolify, not runtime — it is
  inlined into `metadataBase`, and without it every canonical and OG URL says
  `http://localhost:3000`.
- `NEXT_PUBLIC_API_URL` is the same kind of build-time variable, and the backend's
  `CORS_ORIGINS` has to name the deployed frontend origin or every backend tool fails with
  the "Could not reach the server" toast.
- A clean `next build` is worth insisting on: a stale `.next` from an earlier `next dev` run
  left the HMR client and the devtools bundle being served from a *production* server here,
  which cost some time to rule out. `rm -rf .next` before building in CI/Docker.
