# PDFKit

A self-hosted, iLovePDF-style web app offering 10 PDF tools. Workflow: pick files → configure in a right sidebar → big CTA → download. UI takes inspiration from the `iLovePDF/` reference screenshots but does not copy them.

**Always read `STATUS.md` first** — it says which phase is in progress and what's already built. Full phase-by-phase task breakdown lives in `docs/phases/phase-N-*.md`. The original combined plan (kept for reference, not for task tracking) is `docs/PLAN.md`.

## Stack & architecture decisions

| Decision | Choice |
|---|---|
| Frontend | Next.js 15 (App Router, TS, Tailwind, shadcn/ui), no `src/` dir, `@/*` alias |
| Backend | Separate Python FastAPI app, managed with `uv` |
| Processing split | **Browser** (pdf-lib/pdf.js, no upload): Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG (page mode). **Backend**: Compress, OCR, Protect, Unlock, PDF→JPG (extract-images mode) |
| Deployment | Coolify on Hostinger VPS (`zeeshanai.cloud`), two Docker services via `docker-compose.yml` |
| Accounts / storage | None. No user accounts, no persisted files — everything is per-request/ephemeral |
| OCR languages | English only for now; UI reads the language list from `GET /ocr/languages` so more can be added later without a frontend change |
| Upload limit | 50 MB per file, enforced both client-side (fast-fail) and server-side |
| App name | **PDFKit** — kept as a single constant so it's easy to rename |

Local machine has Node 24, Python 3.12, uv, Docker — but **not** Ghostscript/qpdf, so the backend is always run via Docker, in dev and prod alike.

## Repository layout

```
PDFToolkit/
├── frontend/                 Next.js app
├── backend/                  FastAPI app (uv-managed)
├── docker-compose.yml        local dev + Coolify "Docker Compose" resource
├── iLovePDF/                 reference screenshots — keep, don't copy pixel-for-pixel
├── docs/
│   ├── PLAN.md                original full plan (reference only)
│   └── phases/                phase-N-*.md — the actual task breakdown, work from these
├── STATUS.md                  current progress — read this first
└── CLAUDE.md                  this file
```

## Key conventions

- **`lib/tools.ts`** is the single registry for all 10 tools (`{ id, slug, name, tagline, description, icon, accent, multiple, ctaLabel }`). Landing grid, nav, per-page metadata, and "continue to another tool" links all read from it — never hardcode tool info elsewhere.
- **Hydration rule** (global, from `~/.claude/CLAUDE.md`): any component tree using browser-only APIs at init (`crypto.randomUUID()`, canvas, `File`, `window.*`) must be loaded with `next/dynamic` + `{ ssr: false }`. Every tool workspace in this app qualifies.
- **`ToolShell`** owns the `select → configure → processing → done | error` state machine and the three-column layout (canvas + fixed-width right sidebar, sidebar stacks below `lg`). Every tool page is a thin wrapper around it plus a tool-specific options panel.
- Backend passwords (Protect/Unlock) go to `qpdf` via `--password-file`, never as a bare CLI arg — avoids leaking via `ps`.
- Backend subprocess calls go through `app/services/runner.py` (timeout + `Semaphore(MAX_CONCURRENT_JOBS)`), not raw `asyncio.create_subprocess_exec` calls scattered in services.
- Test fixtures (`frontend/test-fixtures/`: a multi-page text PDF, a scanned image-only PDF, a password-protected PDF) are generated once and reused across phases 2–6's manual verification matrices — don't recreate them per phase.

## Working across sessions

Each phase in `docs/phases/` is sized for one session. At the start of a session:
1. Read `STATUS.md` for current phase and any open notes.
2. Read that phase's `docs/phases/phase-N-*.md` for the task list and verification steps.
3. At the end of the session, update `STATUS.md` (progress, decisions made, anything left half-done) before ending — the next session has no memory beyond these two files plus the code itself.

## Deferred/skill notes
- Use the `design-taste-frontend` skill when making UI/visual decisions (Phase 1 landing page, per-tool panels).
- Use the `nextjs-best-practices` and `vercel-react-best-practices` skills where relevant when writing frontend code (data fetching, Server/Client Component boundaries, performance-sensitive components).
- Use the `add-app-to-coolify` skill for the Phase 7 deploy — don't hand-roll Coolify setup steps.
