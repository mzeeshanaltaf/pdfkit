/**
 * The "live now" strip on the admin dashboard: Daytona's own quota-vs-usage numbers, fetched
 * server-side so the dashboard shows sandbox pressure without opening a second tab.
 *
 * There is no cost or history here — `GET /organizations/{orgId}/usage` is the one endpoint
 * Daytona's public API exposes for this, and it returns only a live snapshot
 * (`regionUsage[]`, each with `regionId`, `totalCpuQuota`/`currentCpuUsage` and the
 * memory/disk equivalents — there is no field literally named `region`, which is what used
 * to make this strip always print "(?)"). Everything about spend and per-operation
 * attribution comes from
 * `sandbox_runs` instead (see `queries.ts` and `daytona-pricing.ts`) — this module answers a
 * different question, "is there room right now".
 *
 * **Any failure here must render the strip as unavailable, never fail the dashboard.** The
 * org id is cached per process (`GET /api-keys/current`), since it does not change while the
 * process runs and every usage fetch would otherwise cost two round trips instead of one.
 */

export interface DaytonaUsage {
  region: string;
  cpu: { used: number; quota: number };
  ramGb: { used: number; quota: number };
  diskGb: { used: number; quota: number };
}

let cachedOrgId: string | null = null;

function apiUrl(): string {
  return process.env.DAYTONA_API_URL || "https://app.daytona.io/api";
}

async function fetchJson(path: string, apiKey: string): Promise<unknown | null> {
  try {
    const res = await fetch(`${apiUrl()}${path}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function organizationId(apiKey: string): Promise<string | null> {
  if (cachedOrgId) return cachedOrgId;
  const data = (await fetchJson("/api-keys/current", apiKey)) as
    | { organizationId?: string }
    | null;
  cachedOrgId = data?.organizationId ?? null;
  return cachedOrgId;
}

function firstRegion(data: unknown): Record<string, unknown> | null {
  if (!data || typeof data !== "object") return null;
  const regions = (data as { regionUsage?: unknown }).regionUsage;
  if (!Array.isArray(regions) || regions.length === 0) return null;
  return regions[0] as Record<string, unknown>;
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** `null` means "show the strip as unavailable" — an unset key, an org lookup failure, or the
 *  usage call itself failing. Never throws. */
export async function fetchDaytonaUsage(): Promise<DaytonaUsage | null> {
  const apiKey = process.env.DAYTONA_API_KEY;
  if (!apiKey) return null;

  const orgId = await organizationId(apiKey);
  if (!orgId) return null;

  const region = firstRegion(await fetchJson(`/organizations/${orgId}/usage`, apiKey));
  if (!region) return null;

  return {
    region: typeof region.regionId === "string" ? region.regionId : "?",
    cpu: { used: num(region.currentCpuUsage), quota: num(region.totalCpuQuota) },
    ramGb: { used: num(region.currentMemoryUsage), quota: num(region.totalMemoryQuota) },
    diskGb: { used: num(region.currentDiskUsage), quota: num(region.totalDiskQuota) },
  };
}
