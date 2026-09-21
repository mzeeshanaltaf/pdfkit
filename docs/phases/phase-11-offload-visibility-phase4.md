# Phase 11 (part 4) — Offload visibility: placement in the admin dashboard

## Goal

Extend the admin dashboard's "Browser vs server" split so it doesn't stop at "server" —
report a VPS-vs-sandbox split of server-side runs, and show placement on the recent-runs
table.

## Prerequisites

- Phase 1 (`docs/phases/phase-11-offload-visibility-phase1.md`) — the `X-Processed-On`
  response header is what the frontend reads to know placement for a given run.
- Phase 3 (`docs/phases/phase-11-offload-visibility-phase3.md`) — the `alter table
  pdfkit.tool_runs add column if not exists placement text` migration must already have
  shipped, since this phase reads and writes that column.

## 1. Record placement on every run event

- **`RunEvent`** (`frontend/lib/stats/record.ts:3-13`) gains
  `placement?: "server" | "sandbox" | null`. `ToolShell` passes its state (from Phase 1)
  at all four `recordRun` call sites.
- **`app/api/stats/event/route.ts`** validates it against the two literals (anything else
  → `null`) and adds it to the insert at lines 70-88. Browser-side tools send nothing and
  store `null`, which is correct: the split is about server work only.

## 2. Query and surface it

- **`queries.ts`** gains `fetchPlacementSplit` — a near-copy of `fetchRuntimeSplit`
  (148-160) filtered to `placement is not null` — added to the `Promise.all` in
  `getDashboardData` (229-236).
- **`fetchRecentRuns`** (175-193) adds `placement` to its select and its row mapping.
- **`frontend/components/admin/placement-split.tsx`** — a direct sibling of
  `runtime-split.tsx`, same stacked bar and legend, labels **"On the VPS"** / **"In a
  Daytona sandbox"**. Section title **"VPS vs sandbox"**, description *"Of the work that
  reaches the server, how much left the VPS."*
- **`runs-table.tsx`** — placement folds into the existing **Runtime** cell as a subtle
  second line (`Backend` / `· sandbox`) rather than becoming an eighth column. That table
  already needs a horizontal scroll container, and a column that is empty for every
  browser-side row earns its width poorly.

## Files

**Frontend** — `lib/stats/{record,queries}.ts`, `app/api/stats/event/route.ts`,
`components/admin/placement-split.tsx` (new), `components/admin/runs-table.tsx`,
`app/(admin)/admin/page.tsx`.

## Testing

- `app/api/stats/event/route.ts` — a record with an invalid `placement` value is stored
  as `null`, not rejected outright (browser-side tools must keep working unchanged).
- `fetchPlacementSplit` returns a split that excludes rows where `placement is null`.

## Verification

1. Re-run the OCR batches from Phases 1–3 (one offloaded, one forced to fall back via a
   bad `DAYTONA_SNAPSHOT`) and confirm both land correctly split in the admin dashboard.
2. Admin dashboard shows the VPS-vs-sandbox split section, and the recent-runs table shows
   `· sandbox` under Runtime for the offloaded run and nothing extra for the local one.
3. Browser-side tool runs (Merge, Split, etc.) still show up in "Browser vs server" with
   no placement noise — confirming `null` placement doesn't leak into the new split.
