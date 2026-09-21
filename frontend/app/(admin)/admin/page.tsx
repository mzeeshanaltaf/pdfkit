import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { DayChart } from "@/components/admin/day-chart";
import { FailuresTable } from "@/components/admin/failures-table";
import {
  formatCount,
  formatDuration,
  formatPercent,
  formatUsd,
} from "@/components/admin/format";
import { NotConfiguredPanel } from "@/components/admin/not-configured-panel";
import { PlacementSplit } from "@/components/admin/placement-split";
import { RangeSelector } from "@/components/admin/range-selector";
import { RuntimeSplit } from "@/components/admin/runtime-split";
import { RunsTable } from "@/components/admin/runs-table";
import { SandboxUsage } from "@/components/admin/sandbox-usage";
import { StatTile } from "@/components/admin/stat-tile";
import { ToolBarList } from "@/components/admin/tool-bar-list";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ADMIN_COOKIE_NAME, verifySession } from "@/lib/admin/session";
import { statsEnabled } from "@/lib/db";
import { formatBytes } from "@/lib/format";
import { fetchDaytonaUsage } from "@/lib/stats/daytona-usage";
import { getDashboardData, isStatsRange, toolBreakdownWithZeros } from "@/lib/stats/queries";

export const metadata: Metadata = {
  title: "Admin",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

type Props = {
  searchParams: Promise<{ range?: string }>;
};

export default async function AdminDashboardPage({ searchParams }: Props) {
  // Middleware already gates `/admin/:path*`, but it is a redirect convenience, not the
  // only gate — this page re-checks the session itself.
  const cookieStore = await cookies();
  const session = await verifySession(cookieStore.get(ADMIN_COOKIE_NAME)?.value);
  if (!session) redirect("/admin/login?next=/admin");

  const { range: rawRange } = await searchParams;
  const range = isStatsRange(rawRange) ? rawRange : "7d";

  if (!statsEnabled()) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <DashboardHeader />
        <div className="mt-8">
          <NotConfiguredPanel />
        </div>
      </div>
    );
  }

  let data: Awaited<ReturnType<typeof getDashboardData>>;
  try {
    data = await getDashboardData(range);
  } catch (error) {
    console.error("[admin] failed to load dashboard data:", error);
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <DashboardHeader />
        <div className="mt-8">
          <NotConfiguredPanel reason="The stats database could not be reached. Check the server logs." />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <DashboardHeader />
        <div className="mt-8">
          <NotConfiguredPanel />
        </div>
      </div>
    );
  }

  const {
    overview,
    toolBreakdown,
    runtimeSplit,
    failures,
    recentRuns,
    runsPerDay,
    sandboxOverview,
    sandboxByOperation,
    placementSplit,
  } = data;
  const breakdown = toolBreakdownWithZeros(toolBreakdown);
  const daytonaUsage = await fetchDaytonaUsage();

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <DashboardHeader />

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <RangeSelector current={range} />
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <StatTile label="Total runs" value={formatCount(overview.totalRuns)} />
        <StatTile label="Files processed" value={formatCount(overview.totalFiles)} />
        <StatTile label="Pages processed" value={formatCount(overview.totalPages)} />
        <StatTile
          label="Success rate"
          value={formatPercent(overview.doneRuns, overview.totalRuns)}
        />
        <StatTile label="Data in" value={formatBytes(overview.totalBytesIn)} />
        <StatTile label="Data out" value={formatBytes(overview.totalBytesOut)} />
        <StatTile
          label="Saved by Compress"
          value={overview.compressBytesSaved > 0 ? formatBytes(overview.compressBytesSaved) : "—"}
        />
        <StatTile label="Unique visitors" value={formatCount(overview.uniqueVisitors)} />
        <StatTile label="Median duration" value={formatDuration(overview.medianDurationMs)} />
        <StatTile label="p95 duration" value={formatDuration(overview.p95DurationMs)} />
      </div>

      <Tabs defaultValue="overview" className="mt-8">
        <div className="no-scrollbar overflow-x-auto">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="placement">Placement &amp; Sandbox</TabsTrigger>
            <TabsTrigger value="runs">Runs &amp; Failures</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="overview">
          <Section title="Runs per day" description="Last 30 calendar days.">
            <DayChart rows={runsPerDay} />
          </Section>

          <Section title="Most-used tools">
            <ToolBarList rows={breakdown} totalRuns={overview.totalRuns} />
          </Section>
        </TabsContent>

        <TabsContent value="placement">
          <Section title="Browser vs Server" description="The privacy claim, quantified.">
            <RuntimeSplit rows={runtimeSplit} />
          </Section>

          <Section
            title="VPS vs Sandbox"
            description="Of the backend runs above, how much of that work stayed on the VPS versus offloaded to a Daytona sandbox."
          >
            <PlacementSplit rows={placementSplit} />
          </Section>

          <Section
            title="Sandbox usage"
            description="What offloaded runs cost, reconstructed from each sandbox's own lifetime — not Daytona's Spending dashboard, which lags real consumption by up to 48 hours."
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile label="Sandboxes" value={formatCount(sandboxOverview.sandboxes)} />
              <StatTile
                label="Sandbox time"
                value={formatDuration(sandboxOverview.aliveSeconds * 1000)}
              />
              <StatTile label="CPU-hours" value={sandboxOverview.cpuHours.toFixed(2)} />
              <StatTile label="RAM GB-hours" value={sandboxOverview.ramGbHours.toFixed(2)} />
              <StatTile label="Disk GB-hours" value={sandboxOverview.diskGbHours.toFixed(2)} />
              <StatTile label="Est. cost" value={formatUsd(sandboxOverview.estimatedCostUsd)} />
            </div>

            <h3 className="mt-6 text-sm font-medium text-muted-foreground">By operation</h3>
            <div className="mt-3">
              <SandboxUsage rows={sandboxByOperation} />
            </div>

            <p className="mt-4 text-xs text-muted-foreground">
              {daytonaUsage ? (
                <>
                  Live now: {formatCount(Math.round(daytonaUsage.cpu.used))}/
                  {formatCount(Math.round(daytonaUsage.cpu.quota))} vCPU ·{" "}
                  {formatCount(Math.round(daytonaUsage.ramGb.used))}/
                  {formatCount(Math.round(daytonaUsage.ramGb.quota))} GiB RAM ·{" "}
                  {formatCount(Math.round(daytonaUsage.diskGb.used))}/
                  {formatCount(Math.round(daytonaUsage.diskGb.quota))} GiB disk (
                  {daytonaUsage.region})
                </>
              ) : (
                "Live quota unavailable."
              )}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Cost is an estimate derived from each sandbox&apos;s own lifetime, not a bill —
              cross-check against{" "}
              <a
                href="https://app.daytona.io/dashboard/billing/spending"
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-2"
              >
                Daytona&apos;s Spending page
              </a>
              , which lags real consumption by up to 48 hours.
            </p>
          </Section>
        </TabsContent>

        <TabsContent value="runs">
          <Section title="Recent runs" description="Last 50, regardless of the range above.">
            <RunsTable rows={recentRuns} />
          </Section>

          <Section title="Failures" description="All-time totals, regardless of the range above.">
            <FailuresTable rows={failures} />
          </Section>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function DashboardHeader() {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">Admin dashboard</h1>
      <form action="/api/admin/logout" method="post">
        <Button type="submit" variant="ghost" size="sm">
          Sign out
        </Button>
      </form>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="mt-8 rounded-xl border border-border bg-card p-4 sm:p-5">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}
