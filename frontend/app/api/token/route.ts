import { NextRequest, NextResponse } from "next/server";
import { createHmac, randomBytes } from "node:crypto";

import { checkRateLimit, clientIp } from "@/lib/rate-limit";

/**
 * Mints the short-lived token the browser sends to the PDF API.
 *
 * **A cost gate, not a security boundary.** It stops a script using
 * `api.pdfkit.zeeshanai.cloud` as a free PDF service; it does nothing against someone who
 * copies a token out of devtools, and nothing short of user accounts would. This app
 * deliberately has none. The backend says the same thing in `app/services/auth.py`.
 *
 * POST rather than GET so it cannot be cached by construction, and no cookies are involved,
 * so there is no CSRF surface to protect: a forged cross-site POST gets a token the
 * attacker's own page could have minted anyway.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const VERSION = "v1";
const AUDIENCE = process.env.API_TOKEN_AUDIENCE ?? "pdfkit-api";
const TTL_SECONDS = Number(process.env.API_TOKEN_TTL_SECONDS ?? 120);
const SKEW_SECONDS = Number(process.env.API_TOKEN_SKEW_SECONDS ?? 60);

/** Generous: a real user starting five-file batches mints once every few minutes. */
const MINTS_PER_MINUTE = 30;

function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

export async function POST(req: NextRequest) {
  const secret = process.env.API_TOKEN_SECRET;
  if (!secret) {
    // The backend is then almost certainly unauthenticated too, and says so on
    // /health. Refusing here would take the whole site down over it.
    console.error("[token] API_TOKEN_SECRET is not set; the API is unprotected");
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  const { success } = await checkRateLimit(clientIp(req.headers), {
    name: "token",
    limit: MINTS_PER_MINUTE,
    window: "1 m",
  });
  if (!success) {
    return NextResponse.json(
      { error: "rate_limited" },
      { status: 429, headers: { "Retry-After": "60", "Cache-Control": "no-store" } },
    );
  }

  const now = Math.floor(Date.now() / 1000);
  const expires = now + TTL_SECONDS;
  const payload = b64url(
    JSON.stringify({
      exp: expires,
      // Backdated for clock skew between this container and the backend's.
      nbf: now - SKEW_SECONDS,
      aud: AUDIENCE,
      // Carried but never checked server-side: a replay cache buys nothing
      // against a two-minute window.
      jti: randomBytes(8).toString("hex"),
    }),
  );
  const signingInput = `${VERSION}.${payload}`;
  const signature = createHmac("sha256", secret).update(signingInput).digest("base64url");

  return NextResponse.json(
    { token: `${signingInput}.${signature}`, expiresAt: expires * 1000 },
    { headers: { "Cache-Control": "no-store" } },
  );
}
