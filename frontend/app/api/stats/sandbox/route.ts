import { NextRequest, NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";

import { withDb } from "@/lib/db";

/**
 * Ingests one shard's sandbox-lifecycle record from `backend/app/services/sandbox_stats.py`.
 *
 * Mirrors `app/api/stats/event/route.ts` closely — same shape of one try/catch around the
 * whole body, always `204`, every numeric field clamped — but the caller here is the backend
 * over the internal Docker network, not a browser, so this is authenticated by a shared
 * secret instead of rate-limited by IP, and there is no visitor to record.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const OUTCOMES = new Set(["ok", "failed", "abandoned", "cancelled"]);

function clampInt(value: unknown, max: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : 0;
  return Math.min(Math.max(n, 0), max);
}

function clampNumber(value: unknown, max: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.min(Math.max(n, 0), max);
}

/** Fixed-length digest comparison so a wrong secret cannot be narrowed down by timing. */
function safeEqual(a: string, b: string): boolean {
  const digestA = createHash("sha256").update(a).digest();
  const digestB = createHash("sha256").update(b).digest();
  return timingSafeEqual(digestA, digestB);
}

export async function POST(req: NextRequest) {
  try {
    const expected = process.env.STATS_INGEST_SECRET;
    const provided = req.headers.get("x-stats-secret");
    if (!expected || !provided || !safeEqual(provided, expected)) {
      return new NextResponse(null, { status: 204 });
    }

    const body: Record<string, unknown> = await req.json();

    const sandboxId = typeof body.sandboxId === "string" ? body.sandboxId.slice(0, 128) : null;
    const operation = typeof body.operation === "string" ? body.operation.slice(0, 32) : null;
    const outcome =
      typeof body.outcome === "string" && OUTCOMES.has(body.outcome) ? body.outcome : null;
    if (!sandboxId || !operation || !outcome) return new NextResponse(null, { status: 204 });

    const shardIndex = clampInt(body.shardIndex, 63);
    const shardTotal = clampInt(body.shardTotal, 64) || 1;
    const fileCount = clampInt(body.fileCount, 500);
    const aliveSeconds = clampNumber(body.aliveSeconds, 24 * 60 * 60);
    const cpu = clampInt(body.cpu, 128);
    const memoryGb = clampInt(body.memoryGb, 1024);
    const diskGb = clampInt(body.diskGb, 4096);
    const bytesUp = clampInt(body.bytesUp, 100 * 1024 * 1024 * 1024);
    const bytesDown = clampInt(body.bytesDown, 100 * 1024 * 1024 * 1024);

    await withDb(async (client) => {
      await client.query(
        `insert into pdfkit.sandbox_runs
           (sandbox_id, operation, outcome, shard_index, shard_total, file_count,
            alive_seconds, cpu, memory_gb, disk_gb, bytes_up, bytes_down)
         values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
        [
          sandboxId,
          operation,
          outcome,
          shardIndex,
          shardTotal,
          fileCount,
          aliveSeconds,
          cpu,
          memoryGb,
          diskGb,
          bytesUp,
          bytesDown,
        ],
      );
    });
  } catch {
    // A bad body, an unrecognised secret shape, a database error — none of it is the
    // backend's problem to know about; the telemetry contract is "never fail a conversion".
  }

  return new NextResponse(null, { status: 204 });
}
