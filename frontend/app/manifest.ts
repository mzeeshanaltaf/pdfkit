import type { MetadataRoute } from "next";

import { APP_DESCRIPTION, APP_NAME, APP_TAGLINE, BRAND_HEX } from "@/lib/constants";

/**
 * A web app manifest, so the site is installable and so Android/Chrome have a name and
 * icon to use instead of guessing from the title. The icons are the same files the metadata
 * conventions already serve from `app/`.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${APP_NAME} — ${APP_TAGLINE}`,
    short_name: APP_NAME,
    description: APP_DESCRIPTION,
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: BRAND_HEX,
    categories: ["productivity", "utilities"],
    icons: [
      { src: "/icon.svg", type: "image/svg+xml", sizes: "any", purpose: "any" },
      { src: "/apple-icon.png", type: "image/png", sizes: "180x180" },
    ],
  };
}
