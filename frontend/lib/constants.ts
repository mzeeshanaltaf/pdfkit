/** App-wide constants. The name lives here so renaming the product is a one-line change. */
export const APP_NAME = "PDFKit";

export const APP_TAGLINE = "Every PDF tool you need, on one page.";

export const APP_DESCRIPTION =
  "Merge, split, compress, convert and protect PDFs. Most tools run inside your browser, so the file never leaves your computer.";

/** Per-file upload cap for tools that send the file to the backend. Mirrored server-side. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export const MAX_UPLOAD_LABEL = "50 MB";

/**
 * Absolute origin, used to resolve OG and canonical URLs. Coolify sets this at build time;
 * the localhost fallback keeps `next build` working on a machine that has no domain yet.
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"
).replace(/\/+$/, "");

/** The brand teal, as a plain hex — for `themeColor` and the generated OG image, neither
 * of which can read a CSS custom property. Kept in step with `--brand` in globals.css. */
export const BRAND_HEX = "#006e74";
