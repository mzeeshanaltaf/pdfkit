import { Pool, type PoolClient } from "pg";

import { SCHEMA_SQL } from "./stats/schema";

/**
 * Lazy singleton `pg.Pool` against the shared Postgres box the stats schema lives on.
 *
 * `DATABASE_URL` here is Prisma-shaped (`schema=`, `uselibpqcompat=`, `connection_limit=`,
 * `pool_timeout=` in the query string) because it is shared with another app on the same
 * server. Those params mean nothing to `pg` — in particular `schema=pdfkit` does **not**
 * set `search_path`, so every query in this app fully-qualifies `pdfkit.tool_runs` rather
 * than relying on it. The query string is dropped entirely and the pool config is built
 * from the URL's own parts instead of trusting `pg`'s parsing of it.
 */
function buildPoolConfig(url: string) {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: parsed.port ? Number(parsed.port) : 5432,
    user: decodeURIComponent(parsed.username),
    password: decodeURIComponent(parsed.password),
    database: parsed.pathname.replace(/^\//, ""),
    // sslmode=require works against this server but its cert is not verifiable — pass this
    // explicitly rather than letting pg infer something stricter from the query string.
    ssl: { rejectUnauthorized: false },
    // A shared box running ~18 other app schemas. Keep this app's footprint small.
    max: 3,
  };
}

let pool: Pool | null = null;
let schemaReady: Promise<void> | null = null;

/** With no `DATABASE_URL`, the whole feature degrades quietly — see `withDb`. */
export function statsEnabled(): boolean {
  return Boolean(process.env.DATABASE_URL);
}

function getPool(): Pool {
  if (pool) return pool;
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  pool = new Pool(buildPoolConfig(url));
  return pool;
}

/** Runs once per process. Resets on failure so a transient outage does not wedge it forever. */
async function ensureSchema(client: PoolClient): Promise<void> {
  if (!schemaReady) {
    schemaReady = client.query(SCHEMA_SQL).then(
      () => undefined,
      (error: unknown) => {
        schemaReady = null;
        throw error;
      },
    );
  }
  return schemaReady;
}

/**
 * Runs `fn` against a pooled client, having first made sure the schema exists.
 *
 * Returns `null` without touching the network when `DATABASE_URL` is unset — callers decide
 * what "not configured" means for them (silently skip an ingest, or show a panel on the
 * dashboard). A real database error is a different case and is left to throw, so ingest and
 * dashboard call sites can tell "not configured" apart from "broken" if they need to.
 */
export async function withDb<T>(fn: (client: PoolClient) => Promise<T>): Promise<T | null> {
  if (!statsEnabled()) return null;
  const client = await getPool().connect();
  try {
    await ensureSchema(client);
    return await fn(client);
  } finally {
    client.release();
  }
}
