import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/constants";
import { TOOLS, toolHref } from "@/lib/tools";

/**
 * Built from the tool registry, so adding an eleventh tool puts it in the sitemap with no
 * edit here. `lastModified` is the build time: the pages are statically generated, so a
 * deploy is the only thing that can actually change them.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return [
    {
      // No trailing slash: this is what Next resolves the root `canonical: "/"` to, and a
      // sitemap entry that disagrees with the page's own canonical is a duplicate signal.
      url: SITE_URL,
      lastModified,
      changeFrequency: "monthly",
      priority: 1,
    },
    ...TOOLS.map((tool) => ({
      url: `${SITE_URL}${toolHref(tool)}`,
      lastModified,
      changeFrequency: "monthly" as const,
      // Every tool matters equally; leaving them level avoids implying a hierarchy that
      // does not exist. They sit below the homepage only because it links to all of them.
      priority: 0.8,
    })),
  ];
}
