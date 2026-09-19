import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/constants";

/**
 * Nothing on this site is private: there are no accounts, no dashboards and no generated
 * file URLs to hide, so every route is crawlable. The point of this file is the sitemap
 * reference, which is how a crawler that arrives without one finds every tool page.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    // `/api/contact` is the one exception — a POST-only endpoint with nothing to index.
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
