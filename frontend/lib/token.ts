/**
 * Short-lived API tokens, minted by our own Next route.
 *
 * This is a cost gate, not a security boundary: it stops a script using the PDF API as a
 * free service, and it does nothing at all against someone who copies a token out of
 * devtools. Nothing short of user accounts would, and this app deliberately has none.
 *
 * One cache and one in-flight promise, module-level: a five-file run and the parallel
 * requests inside it mint once between them, not once each.
 */

import { ApiError } from "./api";

interface Minted {
  token: string;
  /** Epoch milliseconds. */
  expiresAt: number;
}

let cached: Minted | null = null;
let inFlight: Promise<Minted> | null = null;

/**
 * Re-mint this long before expiry. The token is only checked when a request *starts*, so
 * the margin only has to cover getting the request onto the wire — but an upload that
 * takes a minute to begin is entirely normal on a slow connection.
 */
const REFRESH_MARGIN_MS = 20_000;

function fresh(entry: Minted | null): entry is Minted {
  return entry !== null && entry.expiresAt - Date.now() > REFRESH_MARGIN_MS;
}

async function mint(): Promise<Minted> {
  let response: Response;
  try {
    response = await fetch("/api/token", { method: "POST", cache: "no-store" });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server. Check it is running and try again.", {
      recoverable: true,
    });
  }

  if (!response.ok) {
    // 429 here is our own mint route's limiter, not the backend's.
    const code = response.status === 429 ? "rate_limited" : "auth_invalid";
    throw new ApiError(response.status, code, MINT_MESSAGES[code], { recoverable: true });
  }

  const body = (await response.json()) as { token?: unknown; expiresAt?: unknown };
  if (typeof body.token !== "string" || typeof body.expiresAt !== "number") {
    throw new ApiError(0, "auth_invalid", MINT_MESSAGES.auth_invalid, { recoverable: true });
  }
  return { token: body.token, expiresAt: body.expiresAt };
}

const MINT_MESSAGES: Record<string, string> = {
  rate_limited: "Too many requests from this network. Wait a moment and try again.",
  auth_invalid: "This page needs a refresh before it can talk to the server.",
};

/** The current token, minting or re-minting only when there isn't a usable one. */
export async function getToken(): Promise<string> {
  if (fresh(cached)) return cached.token;
  // Every caller that arrives while a mint is in flight waits on that same mint.
  inFlight ??= mint().finally(() => {
    inFlight = null;
  });
  cached = await inFlight;
  return cached.token;
}

export function clearToken(): void {
  cached = null;
}

/**
 * Run `fn` with a fresh token, and give it exactly one more go if the backend rejects it.
 *
 * Exactly one: a token the backend keeps refusing is a misconfiguration — the two sides
 * holding different secrets — and retrying a misconfiguration in a loop is how a cost gate
 * becomes a denial of service against yourself.
 */
export async function withFreshToken<T>(fn: (token: string) => Promise<T>): Promise<T> {
  try {
    return await fn(await getToken());
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    clearToken();
    return fn(await getToken());
  }
}
