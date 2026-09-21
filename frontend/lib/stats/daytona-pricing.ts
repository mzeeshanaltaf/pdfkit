/**
 * Daytona's published per-second rates, in one place so a rate change is an env edit, not a
 * deploy. Resource-seconds are derived at query time from `sandbox_runs.alive_seconds ×
 * cpu|memory_gb|disk_gb` rather than stored, so these apply to every row uniformly instead of
 * baking today's prices into old ones.
 *
 * Verified against the user's own Daytona dashboard: a row billing `$0.01` for 169 s of a
 * 4 vCPU / 4 GiB / 10 GiB sandbox reproduces to the cent with the defaults below.
 */
export interface DaytonaRates {
  cpuHour: number;
  ramGbHour: number;
  diskGbHour: number;
}

const DEFAULT_RATES: DaytonaRates = {
  cpuHour: 0.0504,
  ramGbHour: 0.0162,
  diskGbHour: 0.000108,
};

function rate(env: string | undefined, fallback: number): number {
  const parsed = env !== undefined && env !== "" ? Number(env) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** Reads the `DAYTONA_PRICE_*` overrides at call time, so a changed env needs no rebuild. */
export function daytonaRates(): DaytonaRates {
  return {
    cpuHour: rate(process.env.DAYTONA_PRICE_CPU_HOUR, DEFAULT_RATES.cpuHour),
    ramGbHour: rate(process.env.DAYTONA_PRICE_RAM_GB_HOUR, DEFAULT_RATES.ramGbHour),
    diskGbHour: rate(process.env.DAYTONA_PRICE_DISK_GB_HOUR, DEFAULT_RATES.diskGbHour),
  };
}

/** `cpuHours`/`ramGbHours`/`diskGbHours` are resource-seconds already divided by 3600. */
export function estimateCostUsd(
  resourceHours: { cpuHours: number; ramGbHours: number; diskGbHours: number },
  rates: DaytonaRates = daytonaRates(),
): number {
  return (
    resourceHours.cpuHours * rates.cpuHour +
    resourceHours.ramGbHours * rates.ramGbHour +
    resourceHours.diskGbHours * rates.diskGbHour
  );
}
