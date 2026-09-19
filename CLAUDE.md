# PDFKit

A self-hosted, iLovePDF-style web app offering 12 PDF tools. Workflow: pick files → configure in a right sidebar → big CTA → download. UI takes inspiration from the `iLovePDF/` reference screenshots but does not copy them.

**Always read `STATUS.md` first** — it says which phase is in progress and what's already built. Full phase-by-phase task breakdown lives in `docs/phases/phase-N-*.md`. The original combined plan (kept for reference, not for task tracking) is `docs/PLAN.md`.

## Stack & architecture decisions

| Decision | Choice |
|---|---|
| Frontend | Next.js 15 (App Router, TS, Tailwind, shadcn/ui), no `src/` dir, `@/*` alias |
| Backend | Separate Python FastAPI app, managed with `uv` |
| Processing split | **Browser** (pdf-lib/pdf.js, no upload): Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG (page mode). **Backend**: Compress, OCR, Protect, Unlock, PDF→JPG (extract-images mode), PDF→Word (pdf2docx), PDF→Markdown (anydoc) |
| Deployment | Coolify on Hostinger VPS (`zeeshanai.cloud`), two Docker services via `docker-compose.yml` |
| Accounts / storage | None. No user accounts, no persisted files — everything is per-request/ephemeral |
| OCR languages | 14 installed (Arabic, Chinese Simplified, Dutch, English, French, German, Hindi, Italian, Japanese, Portuguese, Russian, Spanish, Swedish, Urdu); adding one is a `tesseract-ocr-<code>` line in `backend/Dockerfile` plus a `LANGUAGE_NAMES` entry, never a frontend change — the UI reads `GET /ocr/languages` |
| Upload limit | 50 MB per file, enforced both client-side (fast-fail) and server-side |
| App name | **PDFKit** — kept as a single constant so it's easy to rename |

Local machine has Node 24, Python 3.12, uv, Docker — but **not** Ghostscript/qpdf, so the backend is always run via Docker, in dev and prod alike.

## Repository layout

```
PDFToolkit/
├── frontend/                 Next.js app
├── backend/                  FastAPI app (uv-managed)
├── docker-compose.yml        local dev + Coolify "Docker Compose" resource
├── iLovePDF/                 reference screenshots — local only (gitignored), don't copy pixel-for-pixel
├── docs/
│   ├── PLAN.md                original full plan (reference only)
│   └── phases/                phase-N-*.md — the actual task breakdown, work from these
├── STATUS.md                  current progress — read this first
└── CLAUDE.md                  this file
```

## Key conventions

- **`lib/tools.ts`** is the single registry for all 12 tools (`{ id, slug, name, tagline, description, icon, accent, multiple, ctaLabel, runsIn }`). Landing grid, nav, per-page metadata, and "continue to another tool" links all read from it — never hardcode tool info elsewhere. `runsIn` is `browser | backend | hybrid` and is what decides whether the 50 MB cap applies to a file.
- **Hydration rule** (global, from `~/.claude/CLAUDE.md`): any component tree using browser-only APIs at init (`crypto.randomUUID()`, canvas, `File`, `window.*`) must be loaded with `next/dynamic` + `{ ssr: false }`. Every tool workspace in this app qualifies.
- **`ToolShell`** owns the `select → configure → processing → done | error` state machine and the three-column layout (canvas + fixed-width right sidebar, sidebar stacks below `lg`). Every tool page is a thin wrapper around it plus a tool-specific options panel.
- **SEO surface.** Because every workspace is `ssr: false`, a tool route's crawlable content is entirely server-rendered alongside it: `app/(tools)/<slug>/page.tsx` renders `ToolPage` + `ToolSeoSection` + `ToolJsonLd`. The copy lives in `lib/seo/tool-content.ts` (one entry per `ToolId`: `title`, `h1`, `howTo`, `intro`, `steps`, `faqs`) and is the source of the `<title>`, the page's **single `h1`**, and the FAQ structured data. Headings inside the workspace are `h2`/`h3` for that reason — don't promote one back to `h1`. `robots.ts`, `sitemap.ts` and `llms.txt/route.ts` all generate from the tool registry, so a new tool needs no edit in any of them, only a `TOOL_SEO` entry (the `Record<ToolId, ToolSeo>` type enforces this).
- The footer now renders on **both** route groups. `app/(tools)/layout.tsx` needs it because the header's "All tools" menu is a Radix dropdown whose links are absent from the HTML until it opens, so the footer is a tool page's only crawlable path to the others. `ToolPage` keeps a `min-h-[calc(100svh-4rem)]` floor so the workspace still owns the first viewport.
- Backend passwords (Protect/Unlock) go to `qpdf` via `--password-file`, never as a bare CLI arg — avoids leaking via `ps`.
- Backend subprocess calls go through `app/services/runner.py` (timeout + `Semaphore(MAX_CONCURRENT_JOBS)`), not raw `asyncio.create_subprocess_exec` calls scattered in services.
- Two Python libraries are driven through shims in `app/tools/` rather than their own CLIs: `anydoc_cli.py` (PDF→Markdown, batched) and `pdf2docx_cli.py` (PDF→Word, which patches pdf2docx so it stops deleting the spaces between words on PDFs that position each word separately). Both are launched as `[sys.executable, "-m", "app.tools.<name>", ...]` with `cwd=_PACKAGE_ROOT`. Don't "simplify" either back to the packaged CLI.
- Test fixtures (`frontend/test-fixtures/`: `sample-text.pdf` 5 pages of real text, `sample-scanned.pdf` 2 image-only pages with no text layer, `sample-protected.pdf` the text one encrypted with password `hunter2`) are committed and reused across phases 2–6's manual verification matrices — don't recreate them per phase. `frontend/scripts/make-test-fixtures.mjs` regenerates the first two if they are ever lost; the encrypted one needs qpdf from the backend image (command printed by the script).

## Working across sessions

Each phase in `docs/phases/` is sized for one session. At the start of a session:
1. Read `STATUS.md` for current phase and any open notes.
2. Read that phase's `docs/phases/phase-N-*.md` for the task list and verification steps.
3. At the end of the session, update `STATUS.md` (progress, decisions made, anything left half-done) before ending — the next session has no memory beyond these two files plus the code itself.

## Deferred/skill notes
- Use the `design-taste-frontend` skill when making UI/visual decisions (Phase 1 landing page, per-tool panels).
- Use the `nextjs-best-practices` and `vercel-react-best-practices` skills where relevant when writing frontend code (data fetching, Server/Client Component boundaries, performance-sensitive components).
- Use the `add-app-to-coolify` skill for the Phase 7 deploy — don't hand-roll Coolify setup steps.
