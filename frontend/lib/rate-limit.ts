import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

/**
 * Per-IP sliding windows backed by Upstash Redis, one named limiter per use.
 *
 * Built lazily and memoised so the Redis client is created once per server instance, and
 * only when a request actually arrives — importing this module in a build that has no
 * Upstash credentials must not throw.
 */
type Window = Parameters<typeof Ratelimit.slidingWindow>[1];

const limiters = new Map<string, Ratelimit>();
let redis: Redis | null = null;

function getRedis(): Redis | null {
  if (redis) return redis;

  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;

  redis = new Redis({ url, token });
  return redis;
}

function getLimiter(name: string, limit: number, window: Window): Ratelimit | null {
  const existing = limiters.get(name);
  if (existing) return existing;

  const client = getRedis();
  if (!client) return null;

  const limiter = new Ratelimit({
    redis: client,
    limiter: Ratelimit.slidingWindow(limit, window),
    prefix: `pdfkit:${name}`,
    analytics: false,
  });
  limiters.set(name, limiter);
  return limiter;
}

/**
 * Fails open: with no Upstash credentials configured the request is allowed through.
 * A misconfigured environment should degrade to "no rate limit", never to a dead site —
 * and for token minting the real ceiling is the backend's own per-IP limit anyway.
 */
export async function checkRateLimit(
  identifier: string,
  { name = "contact", limit = 5, window = "10 m" as Window } = {},
): Promise<{ success: boolean }> {
  const rl = getLimiter(name, limit, window);
  if (!rl) return { success: true };

  const { success } = await rl.limit(identifier);
  return { success };
}

/**
 * The caller's address, taken from the **rightmost** untrusted `X-Forwarded-For` entry.
 *
 * Traefik *appends* to this header, so the leftmost entry is whatever the client sent —
 * reading that (as this used to) lets anyone mint unlimited identities with one header and
 * walk straight past the limiter. The last entry is the one our own proxy wrote, and is
 * the only one nobody upstream of us could forge.
 */
export function clientIp(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) {
    const entries = forwarded.split(",").map((entry) => entry.trim()).filter(Boolean);
    if (entries.length > 0) return entries[entries.length - 1];
  }
  return headers.get("x-real-ip") ?? "anonymous";
}
