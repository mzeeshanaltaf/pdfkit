import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/constants";

/**
 * Nothing on this site is meant for a visitor to sign into: there are no user accounts, so
 * every tool page is crawlable. The point of this file is the sitemap reference, which is
 * how a crawler that arrives without one finds every tool page. `/admin` is the one private
 * surface — a password-gated stats dashboard for the operator, not a visitor feature — and
 * is disallowed here on top of never being linked from anywhere public.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    // `/api/` is a second exception — POST-only endpoints with nothing to index.
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/admin", "/admin/"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
