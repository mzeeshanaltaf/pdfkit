# Phase 9 — Admin dashboard at `/admin`

## Goal
A private, password-gated dashboard that answers "is anyone actually using this, and which
tool?" — total runs, which tool is used most, browser-vs-backend split, failures, and
recent activity — without touching the FastAPI backend at all.

## Prerequisites
Phase 8 complete — PDFKit deployed and live, backend behind the token cost gate.

## Context

PDFKit has been live since Phase 7 and has no way to answer "is anyone actually using
this, and which tool?". Umami records page views, but a page view is not a job: it cannot
say how many PDFs were compressed, how many files a run carried, how many bytes Compress
actually saved, or how often a tool failed.

This phase adds a private, password-gated dashboard at `/admin` that answers those
questions, backed by a new `pdfkit` schema on the existing shared Postgres
(`76.13.7.106`, verified reachable — Postgres 17.7; the `pdfkit` schema does **not** exist
yet, so this is greenfield). `/admin` is deliberately absent from every public surface:
no nav link, no footer link, no sitemap entry, `Disallow` in robots.

**Decisions taken up front:**

| Question | Choice |
|---|---|
| Which tools get counted | All 12, reported by the browser from `ToolShell` |
| Visitor identity | `sha256(ip + daily-rotating salt)` — countable, not reversible |
| Admin password | Plaintext `ADMIN_PASSWORD` env var, timing-safe compare |
| Umami traffic data | Not pulled in — tool stats only |

**The honest trade-off in choice 1:** stats are client-reported, so a determined person
could forge events with curl. That is accepted because it is the only way to count the six
browser-side tools at all (Merge, Split, Rotate, Organize, Page numbers, PDF→JPG page
mode never reach the backend), and because one hook in `ToolShell` covers all twelve tools
uniformly with zero per-tool edits. It also leaves the FastAPI backend **completely
untouched** — no new Python dependency, no `uv.lock` regeneration, no Docker rebuild there,
and no new per-process state to collide with the `--workers 1` constraint. Mitigation is
proportionate, not absolute: same-origin, rate-limited, and every field validated against
the tool registry and clamped.

---

## 1. Database

New schema `pdfkit`, one table. DDL lives in `frontend/lib/stats/schema.sql` and is applied
by an idempotent `ensureSchema()` that runs **once per process** on first use, so a deploy
needs no manual migration step.

```sql
create schema if not exists pdfkit;

create table if not exists pdfkit.tool_runs (
  id           bigserial   primary key,
  occurred_at  timestamptz not null default now(),
  tool         text        not null,   -- ToolId, e.g. 'compress', 'page-numbers'
  runs_in      text        not null,   -- 'browser' | 'backend' | 'hybrid'
  outcome      text        not null,   -- 'done' | 'error' | 'cancelled'
  file_count   integer     not null default 0,
  page_count   integer,                -- null when a file list was still loading
  bytes_in     bigint      not null default 0,
  bytes_out    bigint      not null default 0,
  duration_ms  integer,
  error_code   text,                   -- ApiError.code, or a PdfLoadError kind
  visitor      text                    -- sha256(ip + daily salt), never an IP
);

create index if not exists tool_runs_occurred_at_idx on pdfkit.tool_runs (occurred_at desc);
create index if not exists tool_runs_tool_idx        on pdfkit.tool_runs (tool, occurred_at desc);
```

### `frontend/lib/db.ts` (new)

Lazy singleton `pg.Pool`. **Three things the existing `DATABASE_URL` forces:**

1. It carries Prisma-only query params (`schema=`, `uselibpqcompat=`, `connection_limit=`,
   `pool_timeout=`). Strip the query string and build the pool config explicitly — in
   particular `schema=pdfkit` does **not** set `search_path`, so every query must
   fully-qualify `pdfkit.tool_runs`.
2. `sslmode=require` against this server works but the cert is not verifiable, so pass
   `ssl: { rejectUnauthorized: false }` explicitly rather than relying on `pg`'s parsing.
3. `max: 3` — this is a shared box running ~18 other app schemas.

Exports `withDb()` and `statsEnabled()`. With `DATABASE_URL` unset the whole feature
degrades quietly: ingest returns `204`, the dashboard renders a "stats are not configured"
panel. **Stats must never be able to break a tool run.**

Add `pg` + `@types/pg` to `frontend/package.json` (pure JS, traces cleanly into the
`output: "standalone"` bundle — no native module, so the `node:22-alpine` build is safe).

---

## 2. Recording a run — one edit, all twelve tools

`frontend/components/tool/tool-shell.tsx` already owns the entire
`select → configure → processing → done | error` state machine and knows everything needed:
`tool` (id + `runsIn`), `readableFiles` (count, `size`, `pageCount`), and `result.blob.size`.

- `handleSubmit` (`tool-shell.tsx:131`): stamp `runStartRef.current = Date.now()` at the
  top; record `done` after `setResult(output)`; record `error` in both catch branches
  (the recoverable `ApiError` branch at :160 — carrying `error.code` — and the hard-failure
  branch at :169).
- `handleCancel` (`tool-shell.tsx:189`): record `cancelled`. It has to live here, not in
  the catch, for exactly the reason the existing comment gives — the catch returns early on
  an aborted signal.

New `frontend/lib/stats/record.ts` exporting `recordRun(event)`: a fire-and-forget
`fetch("/api/stats/event", { method: "POST", keepalive: true }).catch(() => {})`. No await,
no state, no error surface. `keepalive` matters because "done" often coincides with the
user clicking Download and leaving.

---

## 3. Ingest — `frontend/app/api/stats/event/route.ts` (new)

`runtime = "nodejs"`, `dynamic = "force-dynamic"`. Follows the shape of
`app/api/contact/route.ts`.

- Validate `tool` against `getTool(id)` from `lib/tools.ts` (throws on unknown → reject),
  and derive `runs_in` from the registry server-side rather than trusting the body.
- Whitelist `outcome`; clamp `file_count`, `page_count`, `duration_ms` and both byte
  counts to sane ceilings; truncate `error_code` to 64 chars.
- Rate limit with the existing `checkRateLimit` from `lib/rate-limit.ts`:
  `{ name: "stats", limit: 60, window: "1 m" }`. Fail-open here is correct — this is a
  cost gate, and a dropped stat must never matter.
- `visitor`: `sha256(clientIp(req.headers) + STATS_SALT + utcDateString())`, base64url,
  first 22 chars. Reuse `clientIp` from `lib/rate-limit.ts` (it already reads the rightmost
  `X-Forwarded-For` entry, which is the one Traefik writes). The date component is what
  makes it self-expiring: yesterday's hashes cannot be linked to today's.
- Opportunistic retention: roughly 1 insert in 500 also runs
  `delete from pdfkit.tool_runs where occurred_at < now() - (STATS_RETENTION_DAYS || ' days')::interval`.
- Always returns `204`, even on rejection — a client that gets no signal cannot tune itself.

---

## 4. Admin auth

No new dependency. Reuses the HMAC idiom already proven in `app/api/token/route.ts`.

**`frontend/lib/admin/session.ts` (new)** — `sign(payload)` and `verify(token)` over
`v1.<b64url(json)>.<b64url(hmac-sha256)>`, payload `{ exp, iat, sub, fp }`.
Written against **Web Crypto (`crypto.subtle`)**, not `node:crypto`, so the identical
`verify` runs in both middleware (Edge) and route handlers. `fp` is a short fingerprint of
`ADMIN_PASSWORD` — changing the password therefore invalidates every live session for free.

**`frontend/app/api/admin/login/route.ts` (new)** — dual-mode body parsing and a `303`
redirect for native form posts, exactly like `app/api/contact/route.ts`, so the login form
survives a hydration failure. Compares username and password with
`crypto.timingSafeEqual` over fixed-length digests (never `===` on the raw strings — that
leaks length and prefix through timing). On success sets cookie `pdfkit_admin`:
`httpOnly`, `sameSite: "lax"`, `secure` in production, `path: "/"`, `maxAge` 8 h.

Throttling: `checkRateLimit({ name: "admin-login", limit: 5, window: "15 m" })` **plus** a
module-level in-process counter as a floor. The Upstash limiter fails open by design, which
is right for the contact form and wrong for a password field — the in-process fallback means
an unconfigured or down Upstash never means unlimited guesses.

**`frontend/app/api/admin/logout/route.ts` (new)** — clears the cookie, `303` to
`/admin/login`.

**`frontend/proxy.ts` (new — the project has none today)** — `matcher: ["/admin/:path*"]`,
skipping `/admin/login`. Verifies the cookie, redirects to `/admin/login?next=…` when
missing or expired. The dashboard page re-checks server-side as well: Proxy is a redirect
convenience, not the only gate. (This is Next 16's renamed successor to `middleware.ts` —
same file-convention slot, `middleware()` renamed `proxy()`.)

---

## 5. The dashboard

```
frontend/app/(admin)/layout.tsx           metadata robots:{index:false,follow:false}
frontend/app/(admin)/admin/page.tsx       server component, reads the DB directly
frontend/app/(admin)/admin/login/page.tsx server-rendered form (real action + method)
frontend/components/admin/               stat-tile, tool-bar-list, day-chart, runs-table
```

Two small edits keep the public chrome off it:
- `components/layout/site-header.tsx` is already `"use client"` and calls `usePathname()` —
  add `if (pathname.startsWith("/admin")) return null`.
- The Umami `<Script>` in `app/layout.tsx` is in a server component; wrap it in a tiny
  client `<Analytics />` that returns null on `/admin`, so admin sessions stay out of
  public page-view numbers.

**Range selector** (`?range=24h|7d|30d|all`, default `7d`) as a plain link group — a server
component with `searchParams`, no client state.

**Tiles:** total runs · files processed · pages processed · data in / out · success rate ·
bytes saved by Compress · median and p95 duration · unique visitors.

**Sections:**
- *Runs per day* — 30-day column chart.
- *Most-used tools* — ranked horizontal bars (this is the "which service is used most"
  answer), each row showing runs, files, share, success rate, using the registry's existing
  `ACCENT_TILE_CLASS` colours so the dashboard reads as the same product.
- *Browser vs server* — split by `runs_in`, which is a genuinely interesting number here
  (it is the privacy claim, quantified).
- *Failures* — `error_code` × tool, ordered by count.
- *Recent runs* — last 50 rows: time, tool, files, size in → out, duration, outcome.

**Charting: no new dependency.** The project hand-rolls its HMAC, rate limiting and
validation (no zod, no date-fns, no charting lib), and a column chart plus ranked bars are
CSS/SVG. The `--chart-1..5` tokens in `app/globals.css` are greyscale placeholders,
identical in light and dark — do not build on them without fixing them first; the brand and
accent tokens are already correct in both themes. `recharts` + shadcn `chart` stays the
upgrade path if a chart ever needs interaction.

A `Table` primitive is not installed; add it with the project's own CLI/style
(`npx shadcn@latest add table` — `components.json` is `"style": "radix-nova"` and primitives
import from the unified `radix-ui` package and from bare `"cn"`, **not** from
`@radix-ui/react-*` or `@/lib/utils`). Pasting from the public docs will produce mismatched
imports and a duplicate Radix copy.

**Queries** live in `frontend/lib/stats/queries.ts`, parameterised, one function per section,
run in parallel with `Promise.all`. `export const dynamic = "force-dynamic"` on the page.

---

## 6. Config, docs and the surfaces that claim "no accounts"

New **runtime** env (never `NEXT_PUBLIC_`, never build args — they are read per request, so
rotating them needs no rebuild):

| Var | Notes |
|---|---|
| `DATABASE_URL` | Already in the **repo-root** `.env.local`. Next reads from the app dir, so it must also be added to `frontend/.env.local` — the same trap the N8N vars hit. |
| `ADMIN_USERNAME` | |
| `ADMIN_PASSWORD` | |
| `ADMIN_SESSION_SECRET` | `openssl rand -hex 32` |
| `STATS_SALT` | `openssl rand -hex 32` — the visitor-hash salt |
| `STATS_RETENTION_DAYS` | default `365` |

Wire all six into `docker-compose.yml`'s frontend `environment:` block in the existing
`${VAR:-}` form, and document them in `frontend/.env.example`. In production they go into
Coolify as runtime, non-preview variables.

**Edits to surfaces that currently assert there is nothing private here:**
- `app/robots.ts` — `disallow: ["/api/", "/admin", "/admin/"]`, and correct the doc comment
  that says "there are no accounts, no dashboards".
- `app/(site)/privacy/page.tsx` — one honest paragraph: anonymous per-run counters are kept,
  with a daily-rotating one-way visitor hash, no IP addresses and still no files.
- `app/llms.txt/route.ts` — "Accounts: none" is still true for visitors; adjust the wording
  so it is not contradicted by an admin login existing.
- `app/sitemap.ts` needs **no** change — it is an allowlist built from `TOOLS`.

**Project bookkeeping** (per `CLAUDE.md`'s working-across-sessions convention): update
`STATUS.md` at the end of the session.

---

## Verification

**Database**
1. First hit to `/api/stats/event` creates the schema; confirm with the same read-only
   container check already used here:
   `docker run --rm -e PGURL=… postgres:17.4 psql "$PGURL" -c "\d pdfkit.tool_runs"`.
2. Confirm `visitor` holds a 22-char hash and no row anywhere contains an IP address.

**Ingest, against `next dev` on port 3000** (port 3000 matters — `CORS_ORIGINS` defaults to
localhost:3000 only):
3. Run Merge (browser) and Compress (backend, via `docker compose up`) and confirm one row
   each with the right `tool`, `runs_in`, `file_count`, `bytes_in`/`bytes_out`, `duration_ms`.
4. Cancel an OCR mid-run → one `cancelled` row. Force a failure (wrong Unlock password) →
   one `error` row carrying the code.
5. `curl` the ingest route with `tool: "not-a-tool"`, a negative `file_count` and a 10 MB
   `error_code` → rejected/clamped, `204`, no bad row written.
6. Stop the database (or unset `DATABASE_URL`) and run a tool end to end → **the tool still
   works and shows no error**. This is the non-negotiable one.

**Auth**
7. `/admin` while logged out → redirect to `/admin/login`. Wrong password ×6 → throttled.
   Correct password → dashboard; cookie is `HttpOnly` and `SameSite=Lax` in devtools.
8. Change `ADMIN_PASSWORD` and restart → the existing cookie no longer authenticates
   (the `fp` binding).
9. `curl -s localhost:3000/admin` with no cookie → a redirect, not dashboard HTML.
   `curl localhost:3000/robots.txt` → `/admin` disallowed.

**Dashboard**
10. Seed ~200 synthetic rows across tools and dates; confirm every tile, the two charts, the
    failures table and the recent-runs table are right, and that the range selector changes
    all of them.
11. 390 px viewport, light and dark, `scrollWidth === clientWidth` (the tables in their own
    `overflow-x` container).
12. Empty state: truncate the table → no crash, no `NaN`, a real "no runs yet" panel.

**Gates**
13. `npm run lint`, `npx tsc --noEmit`, `npm run build` all clean, and `/admin` is absent
    from `sitemap.xml`.
14. `docker compose --profile test run --rm backend-tests` → still **166 passed**. The
    backend is untouched by this phase; this run is the proof of that.
