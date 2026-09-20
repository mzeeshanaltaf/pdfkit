"use client";

import Script from "next/script";
import { usePathname } from "next/navigation";

/**
 * Wraps the Umami tracker so admin sessions stay out of public page-view numbers. Has to be
 * a client component to read the pathname — `app/layout.tsx` itself is a server component,
 * which is why this exists rather than an inline check there.
 */
export function Analytics() {
  const pathname = usePathname();
  if (pathname.startsWith("/admin")) return null;
  if (!process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID) return null;

  return (
    <Script
      src={process.env.NEXT_PUBLIC_UMAMI_SCRIPT_URL}
      data-website-id={process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID}
      strategy="afterInteractive"
    />
  );
}
