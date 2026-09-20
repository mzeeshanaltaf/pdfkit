import { NextRequest, NextResponse } from "next/server";
import { createHash } from "node:crypto";

import { withDb } from "@/lib/db";
import { checkRateLimit, clientIp } from "@/lib/rate-limit";
import { getTool, type ToolId } from "@/lib/tools";

/**
 * Ingests one `recordRun` event from `ToolShell`.
 *
 * **Stats must never be able to break a tool run.** Every code path here — a bad body, an
 * unknown tool, a rate limit, a database outage — ends in the same `204`, and the whole
 * handler body is one try/catch for exactly that reason: a client that gets no signal
 * cannot tune itself against this endpoint, which is also why there is nothing here worth
 * scripting against.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const OUTCOMES = new Set(["done", "error", "cancelled"]);

function clampInt(value: unknown, max: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : 0;
  return Math.min(Math.max(n, 0), max);
}

function utcDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * `sha256(ip + daily salt + today's date)`, truncated. Countable — the same visitor hashes
 * the same for every event today — but not reversible, and self-expiring: yesterday's
 * hashes cannot be linked to today's because the date is baked into the digest.
 */
function visitorHash(ip: string): string {
  const salt = process.env.STATS_SALT ?? "";
  return createHash("sha256")
    .update(`${ip}${salt}${utcDateString()}`)
    .digest("base64url")
    .slice(0, 22);
}

export async function POST(req: NextRequest) {
  try {
    const body: Record<string, unknown> = await req.json();

    const toolId = typeof body.tool === "string" ? (body.tool as ToolId) : null;
    const tool = toolId ? getTool(toolId) : null; // throws on an unknown id, caught below
    const outcome = typeof body.outcome === "string" && OUTCOMES.has(body.outcome)
      ? body.outcome
      : null;
    if (!tool || !outcome) return new NextResponse(null, { status: 204 });

    const ip = clientIp(req.headers);

    // Fail-open: this is a cost gate, and a dropped stat must never matter.
    const { success } = await checkRateLimit(ip, { name: "stats", limit: 60, window: "1 m" });
    if (!success) return new NextResponse(null, { status: 204 });

    const fileCount = clampInt(body.fileCount, 500);
    const pageCount =
      body.pageCount === null || body.pageCount === undefined
        ? null
        : clampInt(body.pageCount, 100_000);
    const bytesIn = clampInt(body.bytesIn, 500 * 1024 * 1024);
    const bytesOut = clampInt(body.bytesOut, 500 * 1024 * 1024);
    const durationMs = clampInt(body.durationMs, 30 * 60 * 1000);
    const errorCode = typeof body.errorCode === "string" ? body.errorCode.slice(0, 64) : null;

    await withDb(async (client) => {
      await client.query(
        `insert into pdfkit.tool_runs
           (tool, runs_in, outcome, file_count, page_count, bytes_in, bytes_out, duration_ms, error_code, visitor)
         values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
        [
          tool.id,
          tool.runsIn,
          outcome,
          fileCount,
          pageCount,
          bytesIn,
          bytesOut,
          durationMs,
          errorCode,
          visitorHash(ip),
        ],
      );

      // Opportunistic retention, ~1 insert in 500: no cron, no extra process, and the odds
      // of ever running it twice in the same request are nil.
      if (Math.random() < 1 / 500) {
        const days = clampInt(Number(process.env.STATS_RETENTION_DAYS ?? 365), 3650) || 365;
        await client.query(
          `delete from pdfkit.tool_runs where occurred_at < now() - ($1 || ' days')::interval`,
          [days],
        );
      }
    });
  } catch {
    // Anything above — bad JSON, an unknown tool, a database error — is not this client's
    // problem to know about.
  }

  return new NextResponse(null, { status: 204 });
}
