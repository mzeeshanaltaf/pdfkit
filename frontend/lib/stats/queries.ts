import type { PoolClient } from "pg";

import { withDb } from "@/lib/db";
import { estimateCostUsd } from "@/lib/stats/daytona-pricing";
import { TOOLS, type ToolId, type ToolRuntime } from "@/lib/tools";

export type StatsRange = "24h" | "7d" | "30d" | "all";

export const STATS_RANGES: { value: StatsRange; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "all", label: "All time" },
];

export function isStatsRange(value: string | undefined): value is StatsRange {
  return value === "24h" || value === "7d" || value === "30d" || value === "all";
}

/** `null` means "no filter" — `all`. Passed as a plain interval string, cast in SQL. */
function rangeInterval(range: StatsRange): string | null {
  switch (range) {
    case "24h":
      return "1 day";
    case "7d":
      return "7 days";
    case "30d":
      return "30 days";
    case "all":
      return null;
  }
}

export interface DashboardOverview {
  totalRuns: number;
  totalFiles: number;
  totalPages: number;
  totalBytesIn: number;
  totalBytesOut: number;
  compressBytesSaved: number;
  doneRuns: number;
  uniqueVisitors: number;
  medianDurationMs: number | null;
  p95DurationMs: number | null;
}

export interface ToolBreakdownRow {
  tool: ToolId;
  runs: number;
  files: number;
  doneRuns: number;
}

export interface RuntimeSplitRow {
  runsIn: ToolRuntime;
  runs: number;
  files: number;
}

export interface FailureRow {
  tool: ToolId;
  errorCode: string;
  count: number;
}

export interface RecentRunRow {
  occurredAt: string;
  tool: ToolId;
  runsIn: ToolRuntime;
  outcome: "done" | "error" | "cancelled";
  fileCount: number;
  bytesIn: number;
  bytesOut: number;
  durationMs: number | null;
  errorCode: string | null;
}

export interface RunsPerDayRow {
  day: string;
  runs: number;
}

/** Resource-hours plus the cost estimated from them, at the rates in effect right now. */
export interface SandboxResourceUsage {
  cpuHours: number;
  ramGbHours: number;
  diskGbHours: number;
  estimatedCostUsd: number;
}

export interface SandboxOverview extends SandboxResourceUsage {
  sandboxes: number;
  aliveSeconds: number;
}

export interface SandboxOperationRow extends SandboxResourceUsage {
  operation: string;
  sandboxes: number;
}

export interface DashboardData {
  overview: DashboardOverview;
  toolBreakdown: ToolBreakdownRow[];
  runtimeSplit: RuntimeSplitRow[];
  failures: FailureRow[];
  recentRuns: RecentRunRow[];
  runsPerDay: RunsPerDayRow[];
  sandboxOverview: SandboxOverview;
  sandboxByOperation: SandboxOperationRow[];
}

async function fetchOverview(client: PoolClient, interval: string | null): Promise<DashboardOverview> {
  const { rows } = await client.query(
    `with base as (
       select * from pdfkit.tool_runs
       where ($1::text is null or occurred_at >= now() - $1::interval)
     )
     select
       (select count(*) from base)::int as total_runs,
       (select coalesce(sum(file_count), 0) from base)::bigint as total_files,
       (select coalesce(sum(page_count), 0) from base)::bigint as total_pages,
       (select coalesce(sum(bytes_in), 0) from base)::bigint as total_bytes_in,
       (select coalesce(sum(bytes_out), 0) from base)::bigint as total_bytes_out,
       (select coalesce(sum(bytes_in), 0) - coalesce(sum(bytes_out), 0)
          from base where tool = 'compress' and outcome = 'done')::bigint as compress_bytes_saved,
       (select count(*) from base where outcome = 'done')::int as done_runs,
       (select count(distinct visitor) from base)::int as unique_visitors,
       (select percentile_cont(0.5) within group (order by duration_ms)
          from base where duration_ms is not null) as median_duration_ms,
       (select percentile_cont(0.95) within group (order by duration_ms)
          from base where duration_ms is not null) as p95_duration_ms`,
    [interval],
  );
  const row = rows[0];
  return {
    totalRuns: Number(row.total_runs),
    totalFiles: Number(row.total_files),
    totalPages: Number(row.total_pages),
    totalBytesIn: Number(row.total_bytes_in),
    totalBytesOut: Number(row.total_bytes_out),
    compressBytesSaved: Number(row.compress_bytes_saved),
    doneRuns: Number(row.done_runs),
    uniqueVisitors: Number(row.unique_visitors),
    medianDurationMs: row.median_duration_ms === null ? null : Math.round(Number(row.median_duration_ms)),
    p95DurationMs: row.p95_duration_ms === null ? null : Math.round(Number(row.p95_duration_ms)),
  };
}

async function fetchToolBreakdown(client: PoolClient, interval: string | null): Promise<ToolBreakdownRow[]> {
  const { rows } = await client.query(
    `select tool,
       count(*)::int as runs,
       coalesce(sum(file_count), 0)::bigint as files,
       count(*) filter (where outcome = 'done')::int as done_runs
     from pdfkit.tool_runs
     where ($1::text is null or occurred_at >= now() - $1::interval)
     group by tool
     order by runs desc`,
    [interval],
  );
  return rows.map((row) => ({
    tool: row.tool,
    runs: Number(row.runs),
    files: Number(row.files),
    doneRuns: Number(row.done_runs),
  }));
}

async function fetchRuntimeSplit(client: PoolClient, interval: string | null): Promise<RuntimeSplitRow[]> {
  const { rows } = await client.query(
    `select runs_in,
       count(*)::int as runs,
       coalesce(sum(file_count), 0)::bigint as files
     from pdfkit.tool_runs
     where ($1::text is null or occurred_at >= now() - $1::interval)
     group by runs_in
     order by runs desc`,
    [interval],
  );
  return rows.map((row) => ({ runsIn: row.runs_in, runs: Number(row.runs), files: Number(row.files) }));
}

async function fetchFailures(client: PoolClient, interval: string | null): Promise<FailureRow[]> {
  const { rows } = await client.query(
    `select tool, coalesce(error_code, '(none)') as error_code, count(*)::int as count
     from pdfkit.tool_runs
     where outcome = 'error' and ($1::text is null or occurred_at >= now() - $1::interval)
     group by tool, error_code
     order by count desc
     limit 20`,
    [interval],
  );
  return rows.map((row) => ({ tool: row.tool, errorCode: row.error_code, count: Number(row.count) }));
}

async function fetchRecentRuns(client: PoolClient): Promise<RecentRunRow[]> {
  const { rows } = await client.query(
    `select occurred_at, tool, runs_in, outcome, file_count, bytes_in, bytes_out, duration_ms, error_code
     from pdfkit.tool_runs
     order by occurred_at desc
     limit 50`,
  );
  return rows.map((row) => ({
    occurredAt: new Date(row.occurred_at).toISOString(),
    tool: row.tool,
    runsIn: row.runs_in,
    outcome: row.outcome,
    fileCount: Number(row.file_count),
    bytesIn: Number(row.bytes_in),
    bytesOut: Number(row.bytes_out),
    durationMs: row.duration_ms === null ? null : Number(row.duration_ms),
    errorCode: row.error_code,
  }));
}

/** Always the trailing 30 calendar days, independent of the top range selector — the
 *  selector answers "how much", this answers "on which days". Gaps are filled with 0. */
async function fetchRunsPerDay(client: PoolClient): Promise<RunsPerDayRow[]> {
  const { rows } = await client.query(
    `select date_trunc('day', occurred_at)::date as day, count(*)::int as runs
     from pdfkit.tool_runs
     where occurred_at >= now() - interval '30 days'
     group by 1
     order by 1`,
  );
  const byDay = new Map<string, number>();
  for (const row of rows) {
    byDay.set(new Date(row.day).toISOString().slice(0, 10), Number(row.runs));
  }

  const days: RunsPerDayRow[] = [];
  const today = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - i);
    const key = d.toISOString().slice(0, 10);
    days.push({ day: key, runs: byDay.get(key) ?? 0 });
  }
  return days;
}

/** Turns summed resource-*seconds* into hours plus the cost estimated from them. */
function toResourceUsage(row: {
  cpu_seconds: unknown;
  ram_gb_seconds: unknown;
  disk_gb_seconds: unknown;
}): SandboxResourceUsage {
  const cpuHours = Number(row.cpu_seconds) / 3600;
  const ramGbHours = Number(row.ram_gb_seconds) / 3600;
  const diskGbHours = Number(row.disk_gb_seconds) / 3600;
  return {
    cpuHours,
    ramGbHours,
    diskGbHours,
    estimatedCostUsd: estimateCostUsd({ cpuHours, ramGbHours, diskGbHours }),
  };
}

async function fetchSandboxOverview(
  client: PoolClient,
  interval: string | null,
): Promise<SandboxOverview> {
  const { rows } = await client.query(
    `select
       count(*)::int as sandboxes,
       coalesce(sum(alive_seconds), 0) as alive_seconds,
       coalesce(sum(alive_seconds * cpu), 0) as cpu_seconds,
       coalesce(sum(alive_seconds * memory_gb), 0) as ram_gb_seconds,
       coalesce(sum(alive_seconds * disk_gb), 0) as disk_gb_seconds
     from pdfkit.sandbox_runs
     where ($1::text is null or occurred_at >= now() - $1::interval)`,
    [interval],
  );
  const row = rows[0];
  return {
    sandboxes: Number(row.sandboxes),
    aliveSeconds: Number(row.alive_seconds),
    ...toResourceUsage(row),
  };
}

async function fetchSandboxByOperation(
  client: PoolClient,
  interval: string | null,
): Promise<SandboxOperationRow[]> {
  const { rows } = await client.query(
    `select
       operation,
       count(*)::int as sandboxes,
       coalesce(sum(alive_seconds * cpu), 0) as cpu_seconds,
       coalesce(sum(alive_seconds * memory_gb), 0) as ram_gb_seconds,
       coalesce(sum(alive_seconds * disk_gb), 0) as disk_gb_seconds
     from pdfkit.sandbox_runs
     where ($1::text is null or occurred_at >= now() - $1::interval)
     group by operation
     order by sandboxes desc`,
    [interval],
  );
  return rows.map((row) => ({
    operation: row.operation,
    sandboxes: Number(row.sandboxes),
    ...toResourceUsage(row),
  }));
}

/**
 * Every section's query, run against one pooled client. `pg` queues queries fired on the
 * same client without awaiting between them, so this is genuinely concurrent from the
 * caller's point of view while still using exactly one connection.
 */
export async function getDashboardData(range: StatsRange): Promise<DashboardData | null> {
  const interval = rangeInterval(range);
  return withDb(async (client) => {
    const [
      overview,
      toolBreakdown,
      runtimeSplit,
      failures,
      recentRuns,
      runsPerDay,
      sandboxOverview,
      sandboxByOperation,
    ] = await Promise.all([
      fetchOverview(client, interval),
      fetchToolBreakdown(client, interval),
      fetchRuntimeSplit(client, interval),
      fetchFailures(client, interval),
      fetchRecentRuns(client),
      fetchRunsPerDay(client),
      fetchSandboxOverview(client, interval),
      fetchSandboxByOperation(client, interval),
    ]);
    return {
      overview,
      toolBreakdown,
      runtimeSplit,
      failures,
      recentRuns,
      runsPerDay,
      sandboxOverview,
      sandboxByOperation,
    };
  });
}

/** Every tool in registry order, even ones with zero runs — so the "most-used tools" list
 *  never silently drops a tool nobody has used yet. */
export function toolBreakdownWithZeros(rows: ToolBreakdownRow[]): ToolBreakdownRow[] {
  const byTool = new Map(rows.map((row) => [row.tool, row]));
  return TOOLS.map(
    (tool) => byTool.get(tool.id) ?? { tool: tool.id, runs: 0, files: 0, doneRuns: 0 },
  ).sort((a, b) => b.runs - a.runs);
}
