/** App-wide constants. The name lives here so renaming the product is a one-line change. */
export const APP_NAME = "PDFKit";

export const APP_TAGLINE = "Every PDF tool you need, on one page.";

export const APP_DESCRIPTION =
  "Merge, split, compress, convert and protect PDFs. Most tools run inside your browser, so the file never leaves your computer.";

/** Per-file upload cap for tools that send the file to the backend. Mirrored server-side. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export const MAX_UPLOAD_LABEL = "50 MB";

/**
 * Backend/hybrid tools also cap a whole batch, independent of the per-file cap above —
 * otherwise a caller could still send many max-size files and land far past what the
 * per-file cap was meant to bound. Mirrored server-side (`MAX_FILES_PER_REQUEST` /
 * `MAX_BATCH_MB` in `backend/app/config.py`).
 */
export const MAX_FILES_PER_BATCH = 10;
export const MAX_BATCH_BYTES = 150 * 1024 * 1024;
export const MAX_BATCH_LABEL = "150 MB";

/**
 * Browser tools never touch the server, so there is no cost or timeout to protect — this
 * is purely a courtesy nudge before a very large batch risks choking the tab's own memory.
 * Not enforced: a soft, one-time warning, since what a browser can handle varies a lot by
 * device.
 */
export const BROWSER_SOFT_BATCH_BYTES = 500 * 1024 * 1024;
export const BROWSER_SOFT_BATCH_LABEL = "500 MB";

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
