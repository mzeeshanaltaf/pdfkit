import type { Metadata } from "next";

/**
 * `/admin` is deliberately absent from every public surface — no nav link, no footer link,
 * no sitemap entry — and this is the last line of defence for a crawler that finds it
 * anyway. `robots.ts` also disallows it outright.
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: LayoutProps<"/">) {
  return <div className="min-h-svh bg-muted/30">{children}</div>;
}
