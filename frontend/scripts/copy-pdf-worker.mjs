// Copies the pdf.js worker into public/ so pdf.js can load it from a same-origin
// URL at runtime. Runs on postinstall (dev machines and the Docker build alike).
import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);

const WORKER_FILE = "pdf.worker.min.mjs";

try {
  const pdfjsEntry = require.resolve("pdfjs-dist/build/pdf.mjs");
  const source = join(dirname(pdfjsEntry), WORKER_FILE);
  const publicDir = join(process.cwd(), "public");
  await mkdir(publicDir, { recursive: true });
  await copyFile(source, join(publicDir, WORKER_FILE));
  console.log(`[copy-pdf-worker] public/${WORKER_FILE}`);
} catch (error) {
  console.error(`[copy-pdf-worker] failed: ${error.message}`);
  process.exitCode = 1;
}
