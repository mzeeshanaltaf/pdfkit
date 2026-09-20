import { NextRequest, NextResponse } from "next/server";

import { ADMIN_COOKIE_NAME, verifySession } from "@/lib/admin/session";

/**
 * A redirect convenience, not the only gate — `app/(admin)/admin/page.tsx` re-checks the
 * session server-side too. `lib/admin/session.ts` is written against Web Crypto rather than
 * `node:crypto` so the identical `verifySession` works everywhere Proxy might run, even
 * though Next 16's Proxy defaults to the Node.js runtime (the renamed successor to
 * Middleware — see the "middleware" file convention's deprecation notice).
 */
export const config = {
  matcher: ["/admin/:path*"],
};

export async function proxy(req: NextRequest) {
  if (req.nextUrl.pathname === "/admin/login") return NextResponse.next();

  const token = req.cookies.get(ADMIN_COOKIE_NAME)?.value;
  const session = await verifySession(token);
  if (session) return NextResponse.next();

  const loginUrl = new URL("/admin/login", req.url);
  loginUrl.searchParams.set("next", req.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}
