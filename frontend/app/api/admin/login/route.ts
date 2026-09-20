import { NextRequest, NextResponse } from "next/server";
import { createHash, timingSafeEqual } from "node:crypto";

import { ADMIN_COOKIE_NAME, createSession } from "@/lib/admin/session";
import { SITE_URL } from "@/lib/constants";
import { checkRateLimit, clientIp } from "@/lib/rate-limit";

/**
 * Same dual-mode body parsing and 303-redirect-for-native-posts idiom as
 * `app/api/contact/route.ts`, so the login form survives a hydration failure — a
 * "use client" form can render correct HTML and still fail to hydrate silently, and a
 * password field is exactly the wrong place to discover that.
 *
 * Every redirect below is built from `SITE_URL`, never from `req.url`. In the standalone
 * Docker image the server listens on `HOSTNAME=0.0.0.0`, and behind Traefik a Route
 * Handler's `req.url` can resolve its origin from that bind address rather than the
 * original `Host` header — unlike `proxy.ts`, which reads the request's `Host` correctly.
 * A login form with no client-side fallback always takes this redirect path, so it must
 * not depend on the host Next thinks it's running on.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 5;

/**
 * A floor under the Upstash limiter, which fails open by design. That is right for the
 * contact form and wrong for a password field: an unconfigured or down Upstash must never
 * mean unlimited guesses. Per-process, not persisted — a restart clears it, which is an
 * acceptable trade for zero extra infrastructure on a single-instance deploy.
 */
const attempts = new Map<string, { count: number; resetAt: number }>();

function allowAttempt(ip: string): boolean {
  const entry = attempts.get(ip);
  return !entry || entry.resetAt < Date.now() || entry.count < MAX_ATTEMPTS;
}

function recordFailedAttempt(ip: string): void {
  const now = Date.now();
  const entry = attempts.get(ip);
  if (!entry || entry.resetAt < now) {
    attempts.set(ip, { count: 1, resetAt: now + WINDOW_MS });
  } else {
    entry.count += 1;
  }
}

/** Fixed-length digest comparison so a wrong guess cannot be narrowed down by timing. */
function safeEqual(a: string, b: string): boolean {
  const digestA = createHash("sha256").update(a).digest();
  const digestB = createHash("sha256").update(b).digest();
  return timingSafeEqual(digestA, digestB);
}

interface Credentials {
  username: string;
  password: string;
}

async function parseBody(req: NextRequest): Promise<Credentials> {
  const contentType = req.headers.get("content-type") ?? "";
  if (
    contentType.includes("application/x-www-form-urlencoded") ||
    contentType.includes("multipart/form-data")
  ) {
    const fd = await req.formData();
    return {
      username: ((fd.get("username") as string | null) ?? "").trim(),
      password: (fd.get("password") as string | null) ?? "",
    };
  }
  const body = await req.json();
  return {
    username: String(body.username ?? "").trim(),
    password: String(body.password ?? ""),
  };
}

export async function POST(req: NextRequest) {
  const isFormPost = (req.headers.get("content-type") ?? "").includes("urlencoded");
  const nextParam = new URL(req.url).searchParams.get("next");
  const redirectTo = nextParam && nextParam.startsWith("/admin") ? nextParam : "/admin";

  const fail = (error: string, status: number) =>
    isFormPost
      ? NextResponse.redirect(new URL(`/admin/login?error=${error}`, SITE_URL), 303)
      : NextResponse.json({ success: false }, { status });

  const ip = clientIp(req.headers);

  if (!allowAttempt(ip)) {
    return fail("throttled", 429);
  }
  const { success: underUpstashLimit } = await checkRateLimit(ip, {
    name: "admin-login",
    limit: MAX_ATTEMPTS,
    window: "15 m",
  });
  if (!underUpstashLimit) {
    recordFailedAttempt(ip);
    return fail("throttled", 429);
  }

  let credentials: Credentials;
  try {
    credentials = await parseBody(req);
  } catch {
    return fail("parse", 400);
  }

  const expectedUsername = process.env.ADMIN_USERNAME ?? "";
  const expectedPassword = process.env.ADMIN_PASSWORD ?? "";
  if (!expectedUsername || !expectedPassword || !process.env.ADMIN_SESSION_SECRET) {
    console.error("[admin] ADMIN_USERNAME, ADMIN_PASSWORD or ADMIN_SESSION_SECRET is not set");
    return fail("not_configured", 503);
  }

  const usernameOk = safeEqual(credentials.username, expectedUsername);
  const passwordOk = safeEqual(credentials.password, expectedPassword);
  if (!usernameOk || !passwordOk) {
    recordFailedAttempt(ip);
    return fail("invalid", 401);
  }

  const { token, maxAge } = await createSession(expectedUsername);
  const res = isFormPost
    ? NextResponse.redirect(new URL(redirectTo, SITE_URL), 303)
    : NextResponse.json({ success: true });
  res.cookies.set(ADMIN_COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  });
  return res;
}
