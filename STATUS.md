# Status

Last updated: 2026-09-18

## Current phase

**Phase 0 — Scaffold** — not started.

See [`docs/phases/phase-0-scaffold.md`](docs/phases/phase-0-scaffold.md) for the task list.

## Phase checklist

- [ ] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [ ] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [ ] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
- [ ] Phase 3 — Browser tools batch 2 (PDF→JPG page mode, Organize, Page Numbers)
- [ ] Phase 4 — Backend services (Compress, Protect, Unlock, OCR, Extract images) + tests
- [ ] Phase 5 — Wire backend tools into UI
- [ ] Phase 6 — Polish (responsive, metadata, edge cases, a11y)
- [ ] Phase 7 — Deploy to Coolify

## Repo state

- No git repo initialized yet.
- `docs/` and `iLovePDF/` (reference screenshots) exist; nothing else.

## Decisions locked in (see `CLAUDE.md` for full detail)

- Stack: Next.js + Tailwind + shadcn/ui frontend, FastAPI backend, two Docker services.
- Hybrid processing: 6 tools browser-only, 5 tools (well, PDF→JPG is split so effectively 5 endpoints) backend-only.
- No accounts, no stored files, 50 MB upload cap, OCR is English-only for now.
- Deploy target: Coolify on the Hostinger VPS, `pdfkit.zeeshanai.cloud` / `api.pdfkit.zeeshanai.cloud`.

## Open questions / risks to watch

- None yet — will fill in as phases surface issues (e.g. Traefik body-size limits, flagged for Phase 7).

## Notes for the next session

- Start with Phase 0. Nothing has been built yet, so there's no prior-session context to reconcile.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker, never `uv run` directly on host.
