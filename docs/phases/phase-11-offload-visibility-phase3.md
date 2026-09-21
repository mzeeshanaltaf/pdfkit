# Phase 11 (part 3) — Offload visibility: sandbox telemetry

## Goal

Record PDFKit's own sandbox telemetry — count, sandbox-time, CPU/RAM/disk-seconds, and
estimated cost — in the stats Postgres, so the admin dashboard can report it without
depending on Daytona's own spending dashboard, which lags real consumption by up to 48
hours and exposes no per-operation attribution at all.

## Prerequisites

Phase 10 complete (`offload._run_shard` exists and is the place that knows a sandbox's
full lifecycle). Independent of Phases 1 and 2's code, though all three ship together as
one effort.

## What the Daytona API actually offers — probed live against the real account

This shapes the whole approach below and is not negotiable:

| Endpoint | With the API key | Returns |
|---|---|---|
| `GET /api-keys/current` | **200** | key permissions + `organizationId` |
| `GET /organizations/{orgId}/usage` | **200** | `regionUsage[]` — **live quota vs current usage** per region/class (`totalCpuQuota`, `currentCpuUsage`, …). No cost, no history, no per-sandbox rows. |
| `GET /sandbox` (+ `labels` filter) | **200** | live sandboxes only |
| `/organizations/{id}`, `/organizations/current`, `/users/me` | 401 | — |
| `/organizations/{id}/spending\|cost\|invoices\|wallet\|billing\|usage/history` | 404 | — |
| `/billing/*`, `/usage` | 404 | — |

The key already carries `read:billing` and `manage:billing`, so this is not a
permissions problem — **the Spending dashboard's data is simply not exposed by the
public API.** No OpenAPI JSON is served either.

But it does not have to be. **Daytona bills exactly `resource × seconds alive`, and
PDFKit knows every sandbox's lifetime.** Verified against the user's own dashboard: the
row showing `676 CPU-s / 676 RAM GB-s / 1690 disk GB-s / $0.01` is 169 s of a 4 vCPU / 4
GiB / 10 GiB sandbox, and Daytona's published rates (vCPU `$0.0504/h`, RAM
`$0.0162/GiB/h`, disk `$0.000108/GiB/h`, billed per second) give `$0.0127` → `$0.01`. So
recording each sandbox's own lifetime reproduces the dashboard to the cent, *immediately*
rather than 48 hours later, and adds the per-operation attribution Daytona can never
give.

## 1. The transport

The stats Postgres belongs to the **Next app** (`DATABASE_URL`, `frontend/lib/db.ts`);
the backend has no database and should not grow one. So the backend **POSTs
fire-and-forget to a new Next route**, exactly as the browser already does for
`tool_runs`:

- `backend/app/services/sandbox_stats.py` — builds one record per shard and posts it to
  `STATS_INGEST_URL` with an `X-Stats-Secret: STATS_INGEST_SECRET` header. Modelled on
  `progress.py`'s contract: **it must never be able to fail a conversion.** Fired as a
  detached `asyncio.Task`, everything caught and logged, disabled entirely when either
  env var is unset.
- `httpx` moves from the dev group to the runtime dependencies in `backend/pyproject.toml`.
  It is already resolved in `uv.lock` as a transitive dependency of `daytona`, so this is
  a declaration, not a new resolution — and relying on a transitive is exactly the kind of
  thing that breaks on a pin bump.
- `frontend/app/api/stats/sandbox/route.ts` — mirrors `app/api/stats/event/route.ts`
  closely: `runtime = "nodejs"`, always `204`, one try/catch around the whole body,
  clamped integers. The differences are that it is authenticated by a constant-time
  compare of the shared secret instead of rate-limited by IP, and it records no visitor.
- **`STATS_INGEST_URL` points at the internal Docker network** —
  `http://frontend:3000/api/stats/sandbox`, the hostname `docker-compose.yml` already
  gives the service. No public round trip, no TLS handshake per sandbox, and the route is
  unreachable from outside the compose network even before the shared secret is checked.
  Both services are already on it (`depends_on: backend`).

Where the record is built: `offload._run_shard`'s `finally` (`offload.py:390-398`), which
is the one place that knows the sandbox id, when it was provisioned, when it was
disposed, and how the shard ended. The `provisioned_at` clock starts after `provision()`
returns and stops before `dispose()` — the same window Daytona bills.

## 2. The table

Appended to `SCHEMA_SQL` in `frontend/lib/stats/schema.ts` **and** mirrored in
`frontend/lib/stats/schema.sql` (they are kept identical by hand today):

```sql
create table if not exists pdfkit.sandbox_runs (
  id            bigserial   primary key,
  occurred_at   timestamptz not null default now(),
  sandbox_id    text        not null,
  operation     text        not null,   -- ocr | word | markdown | compress
  outcome       text        not null,   -- ok | failed | abandoned | cancelled
  shard_index   integer     not null default 0,
  shard_total   integer     not null default 1,
  file_count    integer     not null default 0,
  alive_seconds numeric     not null default 0,
  cpu           integer     not null default 0,   -- vCPU the snapshot carries
  memory_gb     integer     not null default 0,
  disk_gb       integer     not null default 0,
  bytes_up      bigint      not null default 0,
  bytes_down    bigint      not null default 0
);
create index if not exists sandbox_runs_occurred_at_idx on pdfkit.sandbox_runs (occurred_at desc);
```

Resource-seconds and cost are **derived at query time** from `alive_seconds ×
cpu|memory_gb|disk_gb`, not stored — storing a price would bake today's rates into old
rows. The rates live in one place, `frontend/lib/stats/daytona-pricing.ts`, overridable
by `DAYTONA_PRICE_CPU_HOUR` / `_RAM_GB_HOUR` / `_DISK_GB_HOUR` so a rate change is an env
edit, not a deploy.

## 3. The migration — the part that is easy to get wrong

`SCHEMA_SQL` is `create table if not exists` and runs once per process (`db.ts:48-59`).
**An existing deployed `tool_runs` will not gain a new column from it.** So Phase 4's
`placement` column on `tool_runs` must be added as an explicit, idempotent statement in
the same string, added in this phase alongside the `sandbox_runs` table since both are
schema edits to the same file made in the same pass:

```sql
alter table pdfkit.tool_runs add column if not exists placement text;
```

Postgres supports `add column if not exists`, `client.query` takes the multi-statement
string, and it is cheap and safe to re-run every boot. Same mechanism for anything added
later. Phase 4 (`docs/phases/phase-11-offload-visibility-phase4.md`) is what actually
reads and writes this column — this phase only adds it so the migration ships once.

## 4. The panel

A new `Section` on the admin page, above "Browser vs server":

- A row of `StatTile`s reusing the existing component: **Sandboxes**, **Sandbox time**,
  **CPU-hours**, **RAM GB-hours**, **Disk GB-hours**, **Est. cost**. `formatDuration` and
  `formatCount` already exist in `frontend/components/admin/format.ts`.
- **By operation** — `frontend/components/admin/sandbox-usage.tsx`, built on the same
  horizontal-bar idiom as `tool-bar-list.tsx`. No charting dependency; the dashboard is
  hand-rolled CSS by deliberate choice and stays that way.
- **Live now** — a one-line strip from `GET /organizations/{orgId}/usage`, fetched
  server-side in the admin page (`force-dynamic` already) via
  `frontend/lib/stats/daytona-usage.ts`: `0/10 vCPU · 0/10 GiB RAM · 0/30 GiB disk (eu)`.
  `cache: "no-store"`, a short `AbortSignal.timeout`, and **any failure renders the strip
  as unavailable rather than failing the page** — the dashboard must not depend on a
  third-party API being up. The org id comes from `GET /api-keys/current` (cached per
  process), so only `DAYTONA_API_KEY` needs to reach the Next app.
- A footnote naming the estimate as an estimate, and linking to
  `https://app.daytona.io/dashboard/billing/spending` for billed cost, with the 48-hour
  lag stated.

## Explicitly out of scope for this phase

- Placement on the "Browser vs server" split or the recent-runs table — that's Phase 4.

## Files

**Backend** — `app/services/sandbox_stats.py` (new), `app/services/offload.py`
(`_run_shard`), `pyproject.toml`, `.env.example`, `docker-compose.yml`,
`backend/README.md`.

**Frontend** — `lib/stats/{schema,schema.sql}.ts`, `lib/stats/{daytona-pricing,daytona-usage}.ts`
(new), `app/api/stats/sandbox/route.ts` (new), `components/admin/sandbox-usage.tsx` (new),
`app/(admin)/admin/page.tsx`, `frontend/.env.example`.

**New env, all optional and all degrading to "feature off"** — backend:
`STATS_INGEST_URL`, `STATS_INGEST_SECRET`; frontend: `STATS_INGEST_SECRET`,
`DAYTONA_API_KEY`, `DAYTONA_API_URL`, and the three `DAYTONA_PRICE_*` overrides. Added to
both `environment:` blocks in `docker-compose.yml`, to both `.env.example` files, and set
in Coolify. `DAYTONA_API_KEY` reaching the Next app is what the live-quota strip needs; it
is runtime env, never `NEXT_PUBLIC_`.

## Testing

- `backend/tests/test_offload.py` — the telemetry record is built with the right sandbox
  id, operation, and a plausible `alive_seconds`, and a posting failure cannot fail the
  batch.
- A route test for `app/api/stats/sandbox/route.ts` — rejects a missing/wrong
  `X-Stats-Secret`, accepts a well-formed record, always returns `204`, clamps
  out-of-range integers rather than erroring.

## Verification

1. `docker compose run --rm --build backend-tests` green.
2. Run an OCR batch large enough to offload (from Phase 1/2's verification) and confirm a
   row lands in `pdfkit.sandbox_runs` with a plausible `alive_seconds`.
3. Admin dashboard shows the new sandbox tiles, the by-operation breakdown, and the "live
   now" strip (or its unavailable state if the Daytona usage call fails — confirm it
   degrades rather than breaking the page).
4. **Cross-check the estimated cost against Daytona's Spending page 48 h later** — the
   arithmetic is expected to agree to the cent, and that is the assertion that says the
   telemetry is right.
5. Migration: `psql -c "\d pdfkit.sandbox_runs"` exists and `psql -c "\d
   pdfkit.tool_runs"` shows the new `placement` column, on a database that already held
   rows before this phase.
