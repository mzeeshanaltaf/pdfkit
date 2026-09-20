# PDFKit

A self-hosted, iLovePDF-style web app with 12 PDF tools. Pick files → configure in
the right sidebar → one big button → download. No accounts, no stored files:
everything is per-request and ephemeral.

Five tools run entirely in the browser (nothing is uploaded); the rest go to a small
FastAPI service that shells out to Ghostscript, qpdf, Tesseract, pdf2docx and anydoc.
Compress also carries two passes of its own, because Ghostscript can do neither: a
font subsetter (a Word document with one emoji in it embeds several megabytes of
unused font) and a content-stream rewriter (pdfwrite makes a vector PDF *bigger*).

| Runs in the browser | Runs on the backend |
|---|---|
| Merge, Split, Rotate, Organize, Page Numbers | Compress, OCR, Protect, Unlock, PDF→Word, PDF→Markdown |

PDF→JPG is the mixed case: page rendering happens in the browser, while extracting the
images already embedded in a document uses the backend.

OCR ships 14 Tesseract models — Arabic, Chinese (Simplified), Dutch, English, French,
German, Hindi, Italian, Japanese, Portuguese, Russian, Spanish, Swedish, Urdu — and up to
three can be combined on one document. Adding a fifteenth is one `tesseract-ocr-<code>`
line in `backend/Dockerfile` (plus a `LANGUAGE_NAMES` entry so it shows a real name
instead of its code); the picker reads `GET /ocr/languages`, so no frontend change. Each
model costs roughly 0.5-6 MB of image size.

## Repository layout

```
frontend/   Next.js 16 app (App Router, TypeScript, Tailwind v4, shadcn/ui)
backend/    FastAPI app, managed with uv
docs/       PLAN.md (reference) and phases/ (the actual task breakdown)
STATUS.md   current progress — read this first
```

## Requirements

- Node 24 (Node 22 in the Docker image)
- Docker Desktop — the backend depends on Ghostscript/qpdf/Tesseract, so it always
  runs in a container, in dev as well as prod
- `uv` (only needed to edit backend dependencies or run its tests on the host)

## Local development

Frontend, on the host with hot reload:

```bash
cd frontend
npm install          # postinstall copies pdf.worker.min.mjs into public/
npm run dev          # http://localhost:3000
```

Backend, in Docker:

```bash
docker compose up backend        # http://localhost:8000
curl localhost:8000/health       # {"status":"ok"}
```

Both services together, as they run in production:

```bash
docker compose up --build
```

Backend tests (dependency resolution only — the native binaries live in the image):

```bash
cd backend && uv run pytest
```

## Environment variables

Copy `.env.example` to `.env` at the repo root for compose, and
`frontend/.env.example` to `frontend/.env.local` for `npm run dev`.

| Variable | Service | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | frontend | `http://localhost:8000` | Baked in at **build** time — the Docker image must be rebuilt to change it |
| `NEXT_PUBLIC_SITE_URL` | frontend | `http://localhost:3000` | Baked in at **build** time. Left unset in production, every canonical URL, OG URL, sitemap entry and `llms.txt` link ships pointing at localhost |
| `NEXT_PUBLIC_UMAMI_SCRIPT_URL` | frontend | *(unset)* | Self-hosted Umami tracker script URL, e.g. `https://analytics.example.com/script.js`. Baked in at **build** time. Optional — unset, `layout.tsx` renders no tracker |
| `NEXT_PUBLIC_UMAMI_WEBSITE_ID` | frontend | *(unset)* | The site's UUID from the Umami dashboard. Baked in at **build** time. Also gates whether the script tag renders at all |
| `CORS_ORIGINS` | backend | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated list of allowed origins |
| `MAX_UPLOAD_MB` | backend | `50` | Per-file cap; the frontend enforces the same number client-side |
| `MAX_OCR_LANGUAGES` | backend | `3` | Most languages one OCR request may combine; the picker mirrors this number |
| `MAX_CONCURRENT_JOBS` | backend | `2` | Concurrent heavy jobs — subprocesses (Ghostscript/qpdf/OCR) and compression's in-process stream rewrite share the limit |
| `JOB_TIMEOUT_SECONDS` | backend | `180` | Wall-clock ceiling for one job; per-operation overrides exist, e.g. `OCR_TIMEOUT_SECONDS` (600), `WORD_TIMEOUT_SECONDS` (300), `MARKDOWN_TIMEOUT_SECONDS` (120) |
| `WORK_DIR` | backend | `/tmp/pdfkit` | Scratch space, mounted as tmpfs in compose |
| `API_TOKEN_SECRET` | **both** | *(unset)* | Signs the short-lived tokens the frontend mints and the backend verifies. **One value, set on both services.** Unset, the API accepts unauthenticated requests and `/health` reports `"auth":"off"`. Runtime env, never a build arg — rotating it needs no rebuild |
| `API_TOKEN_SECRET_PREVIOUS` | backend | *(unset)* | Verify-only. Set to the outgoing value for one deploy when rotating, so tokens already in flight keep working |
| `FORWARDED_ALLOW_IPS` | backend | `172.16.0.0/12,10.0.0.0/8` | Read by uvicorn. Without it every visitor shares one rate-limit bucket — see the deployment gotchas |

## Deployment

**Live** at [pdfkit.zeeshanai.cloud](https://pdfkit.zeeshanai.cloud), API at
`api.pdfkit.zeeshanai.cloud`. Runs on Coolify on the Hostinger VPS (`zeeshanai.cloud`),
as a single **Docker Compose** resource (app uuid `b1s6cgebvkpxxrzzjp2d2244`, project
"PDFKit") built from this repo's `docker-compose.yml`.

Build-time args (frontend): `NEXT_PUBLIC_API_URL=https://api.pdfkit.zeeshanai.cloud`,
`NEXT_PUBLIC_SITE_URL=https://pdfkit.zeeshanai.cloud`,
`NEXT_PUBLIC_UMAMI_SCRIPT_URL=https://analytics.zeeshanai.cloud/script.js`,
`NEXT_PUBLIC_UMAMI_WEBSITE_ID=<uuid>` (self-hosted Umami; the site's dashboard traffic
lives at analytics.zeeshanai.cloud). Runtime (backend):
`CORS_ORIGINS=https://pdfkit.zeeshanai.cloud`. The contact form's four vars
(`N8N_CONTACT_WEBHOOK_URL`, `N8N_API_KEY`, `UPSTASH_REDIS_REST_URL`,
`UPSTASH_REDIS_REST_TOKEN`) are frontend runtime vars, set directly in Coolify rather than
in the compose file.

**`docker-compose.yml` publishes no host ports** (`expose`, not `ports`) — Coolify's
Traefik reaches both containers over the internal Docker network via its own labels, and
a host-published port collided with Coolify's own dashboard, which already binds host
`8000`. `docker-compose.override.yml` adds `3000:3000` / `8000:8000` back for local dev
only; `docker compose up` merges it automatically, and Coolify never reads it (it's
pointed at `docker-compose.yml` alone).

**Redeploying**: push to `main`. `.github/workflows/deploy.yml` calls Coolify's deploy API
with retries (Coolify's own git-push webhook is fire-once and silently drops a deploy on a
transient 502, so it's turned off for this app). To redeploy without a code change, re-run
that workflow from the Actions tab, or `POST /api/v1/deploy?uuid=b1s6cgebvkpxxrzzjp2d2244`
against the Coolify API directly.

**Logs**: Coolify's dashboard (Application → pdfkit → Logs) for build logs, or
`docker logs <frontend|backend>-b1s6cgebvkpxxrzzjp2d2244-<hash>` on the VPS for the
running containers. `docker ps --filter name=b1s6cgebvkpxxrzzjp2d2244` finds the current
container names (they change every deploy).

**The API is a cost gate, not an open service.** Every processing endpoint needs a bearer
token minted by the frontend's `/api/token`, and is rate-limited per IP (20/min and
120/hour for jobs, 240/min coarse). `/health` and `GET /ocr/languages` are deliberately
open — Traefik cannot mint a token, and the language picker fetches its list before the
user has done anything. This stops scripted third-party use; it does **not** stop someone
copying a token out of devtools, and nothing short of user accounts would. Set
`API_TOKEN_SECRET` to the same `openssl rand -hex 32` value on both services in Coolify.

**Known-good gotchas, already handled** — don't re-break these:
- Traefik on this instance has no body-size limit or custom read/idle timeout configured,
  so the 50 MB upload cap and the ~900 s worst-case PDF-to-Word-with-OCR request are both
  bounded only by the backend's own timeouts (a `504 processing_timed_out` from the app,
  never a silent proxy cutoff). If that ever changes, both need re-verifying.
- The frontend Docker build uses `npm install`, not `npm ci` — the committed lockfile is
  resolved on Windows dev machines and drops Linux-only optional deps, which `npm ci`
  refuses to reconcile.
- The backend's `/tmp/pdfkit` tmpfs mount pins `uid=1001,gid=1001,mode=0700` explicitly;
  a bare tmpfs mount masks the image's chown and every upload 500s.
