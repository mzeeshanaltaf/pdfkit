# Status

Last updated: 2026-09-18

## Current phase

**Phase 0 — Scaffold** — ✅ complete. Next up: **Phase 1 — Shared UI shell**.

See [`docs/phases/phase-1-shared-ui.md`](docs/phases/phase-1-shared-ui.md) for the task list.

## Phase checklist

- [x] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [ ] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [ ] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
- [ ] Phase 3 — Browser tools batch 2 (PDF→JPG page mode, Organize, Page Numbers)
- [ ] Phase 4 — Backend services (Compress, Protect, Unlock, OCR, Extract images) + tests
- [ ] Phase 5 — Wire backend tools into UI
- [ ] Phase 6 — Polish (responsive, metadata, edge cases, a11y)
- [ ] Phase 7 — Deploy to Coolify

## Repo state

- Git repo initialized (`main`), one commit containing the whole scaffold.
- `frontend/` — Next.js 16.3.5, React 19, Tailwind v4, shadcn/ui (all 17 components from
  the Phase 0 list), pdf-lib / pdfjs-dist / dnd-kit / jszip / react-dropzone / file-saver /
  lucide-react installed. Only the default create-next-app page exists so far.
- `backend/` — FastAPI + uvicorn + ocrmypdf/pypdf/pillow via uv; `app/main.py` (CORS +
  `GET /health`), `app/config.py`, one passing test in `tests/test_health.py`.
- `docker-compose.yml`, both Dockerfiles, `.dockerignore` files, root `README.md`,
  `.gitignore`, `.gitattributes`, `.env.example` (root + frontend).

## Phase 0 verification results

All four checks from the phase doc pass:

- `docker compose build` — both images build.
- `docker compose up backend` → `curl localhost:8000/health` → `{"status":"ok"}`;
  inside the image `gs 10.00.0`, `qpdf 11.3.0`, `tesseract 5.3.0`, `pdftoppm 22.12.0`
  all resolve and the process runs as non-root `pdfkit` (uid 1001).
- Frontend container and `npm run dev` both serve 200 at `localhost:3000`, and
  `/pdf.worker.min.mjs` is served (1.27 MB) in dev and in the image.
- `git status` clean; no `node_modules`, `.venv`, `.next` or generated worker tracked.

## Decisions made in Phase 0

- **Next.js 16.3.5**, not 15 — that's what `create-next-app@latest` ships now. Turbopack
  is the default builder. It generates `frontend/AGENTS.md` + `frontend/CLAUDE.md`
  (re-created by `next dev` if deleted) pointing at version-accurate docs bundled in
  `node_modules/next/dist/docs/` — **read those before writing App Router code**, Next 16
  has breaking changes vs. older training data.
- **shadcn CLI is new**: `init` needs `--base radix --preset nova` (style records as
  `radix-nova`, base color neutral). `lib/utils.ts` re-exports `cn` from shadcn's own
  `cn` package instead of `clsx` + `tailwind-merge`.
- **Tailwind v4** — CSS-first config in `app/globals.css`, no `tailwind.config.ts`.
- **`package-lock.json` must be generated on Linux.** A Windows-generated lockfile omits
  musl-only transitive deps (`@emnapi/*`), which breaks `npm ci` in the alpine image.
  After adding deps on Windows, re-run:
  `docker run --rm -v "<repo>\frontend:/app" -w /app node:22-alpine npm install --package-lock-only --ignore-scripts`
- Frontend image installs with `npm ci --ignore-scripts` in the deps stage (postinstall
  needs `scripts/`, which isn't copied there), then runs `npm run postinstall` in the
  builder so the pdf.js worker lands in `public/`.
- `.gitattributes` normalizes line endings to LF — Dockerfiles/scripts must not get CRLF.

## Open questions / risks to watch

- `starlette` warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`.
  Harmless now; revisit if the backend test suite grows in Phase 4.
- Traefik default request body limit vs. the 50 MB upload cap — still flagged for Phase 7.

## Notes for the next session

- Start Phase 1: `lib/tools.ts` registry, landing page, `ToolShell`, dropzone.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker,
  never `uv run` directly on host (`uv run pytest` is fine; it doesn't touch the binaries).
- Remember the hydration rule: every tool workspace must be loaded with
  `next/dynamic` + `{ ssr: false }`.
