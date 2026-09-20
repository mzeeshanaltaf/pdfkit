/**
 * The admin login cookie: `v1.<b64url(json)>.<b64url(hmac-sha256)>`, the same idiom
 * `app/api/token/route.ts` uses for the API's bearer token. Written against Web Crypto
 * (`crypto.subtle`), not `node:crypto`, so the identical `verifySession` runs unmodified in
 * both `proxy.ts` and ordinary route/page handlers.
 */

const VERSION = "v1";
const COOKIE_MAX_AGE_SECONDS = 8 * 60 * 60;
export const ADMIN_COOKIE_NAME = "pdfkit_admin";

export interface AdminSessionPayload {
  sub: string;
  iat: number;
  exp: number;
  /** A short fingerprint of `ADMIN_PASSWORD`, so changing the password invalidates every
   *  live session for free — no session store to clear. */
  fp: string;
}

function b64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const byte of arr) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlToBytes(input: string): Uint8Array<ArrayBuffer> {
  const normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

const encoder = new TextEncoder();

function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

/** Short, non-secret fingerprint of a value — used to bind a session to the current password
 *  without ever putting the password itself in the cookie. */
export async function fingerprint(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return b64url(digest).slice(0, 12);
}

async function sign(payload: AdminSessionPayload, secret: string): Promise<string> {
  const body = b64url(encoder.encode(JSON.stringify(payload)));
  const signingInput = `${VERSION}.${body}`;
  const key = await hmacKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(signingInput));
  return `${signingInput}.${b64url(signature)}`;
}

/** `crypto.subtle.verify` does the signature comparison in constant time — no manual compare. */
async function verify(token: string, secret: string): Promise<AdminSessionPayload | null> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== VERSION) return null;
  const [version, body, signaturePart] = parts;

  const key = await hmacKey(secret);
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    b64urlToBytes(signaturePart),
    encoder.encode(`${version}.${body}`),
  );
  if (!valid) return null;

  try {
    return JSON.parse(new TextDecoder().decode(b64urlToBytes(body))) as AdminSessionPayload;
  } catch {
    return null;
  }
}

/** Signs a fresh 8-hour session for a successful login. */
export async function createSession(username: string): Promise<{ token: string; maxAge: number }> {
  const secret = process.env.ADMIN_SESSION_SECRET ?? "";
  const now = Math.floor(Date.now() / 1000);
  const payload: AdminSessionPayload = {
    sub: username,
    iat: now,
    exp: now + COOKIE_MAX_AGE_SECONDS,
    fp: await fingerprint(process.env.ADMIN_PASSWORD ?? ""),
  };
  return { token: await sign(payload, secret), maxAge: COOKIE_MAX_AGE_SECONDS };
}

/**
 * Verifies a session cookie: valid signature, not expired, and bound to the password
 * currently configured. Reads `ADMIN_SESSION_SECRET` / `ADMIN_PASSWORD` at call time, like
 * every other env-gated check in this app, rather than caching them at import.
 */
export async function verifySession(token: string | undefined | null): Promise<AdminSessionPayload | null> {
  const secret = process.env.ADMIN_SESSION_SECRET;
  if (!token || !secret) return null;

  const payload = await verify(token, secret);
  if (!payload) return null;
  if (payload.exp < Math.floor(Date.now() / 1000)) return null;
  if (payload.fp !== (await fingerprint(process.env.ADMIN_PASSWORD ?? ""))) return null;

  return payload;
}
