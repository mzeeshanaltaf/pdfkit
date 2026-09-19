import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

/**
 * Per-IP sliding window for the contact form, backed by Upstash Redis.
 *
 * Built lazily so the Redis client is created once per server instance, and only when a
 * submission actually arrives — importing this module in a build that has no Upstash
 * credentials must not throw.
 */
let limiter: Ratelimit | null = null;

function getLimiter(): Ratelimit | null {
  if (limiter) return limiter;

  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;

  limiter = new Ratelimit({
    redis: new Redis({ url, token }),
    limiter: Ratelimit.slidingWindow(5, "10 m"),
    prefix: "pdfkit:contact",
    analytics: false,
  });
  return limiter;
}

/**
 * Fails open: with no Upstash credentials configured the submission is allowed through.
 * A misconfigured environment should degrade to "no rate limit", never to a dead form.
 */
export async function checkRateLimit(identifier: string): Promise<{ success: boolean }> {
  const rl = getLimiter();
  if (!rl) return { success: true };

  const { success } = await rl.limit(identifier);
  return { success };
}
