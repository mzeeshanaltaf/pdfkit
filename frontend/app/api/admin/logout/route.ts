import { NextResponse } from "next/server";

import { ADMIN_COOKIE_NAME } from "@/lib/admin/session";
import { SITE_URL } from "@/lib/constants";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Built from `SITE_URL`, not `req.url` — see the note in `app/api/admin/login/route.ts`
 * on why a Route Handler's own request URL can't be trusted for this in the standalone
 * Docker image, behind Traefik.
 */
export async function POST() {
  const res = NextResponse.redirect(new URL("/admin/login", SITE_URL), 303);
  res.cookies.delete(ADMIN_COOKIE_NAME);
  return res;
}
