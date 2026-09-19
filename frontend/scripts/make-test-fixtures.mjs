/**
 * Generates the PDFs used to verify the UI by hand, in frontend/test-fixtures/.
 *
 * They are committed and reused from phase 1 through phase 6, so this only needs running
 * again if a fixture is lost or a new one is needed:
 *
 *   node scripts/make-test-fixtures.mjs
 *
 * Two of the three need tools this machine does not have locally — poppler to turn a page
 * into a bitmap, qpdf to encrypt — so those steps run inside the backend image. Docker is
 * a prerequisite for the backend anyway, in dev as well as prod.
 */
import { spawnSync } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join, resolve, sep } from "node:path";

import { PDFDocument, StandardFonts, rgb } from "pdf-lib";

const OUT_DIR = join(process.cwd(), "test-fixtures");
const REPO_ROOT = resolve(process.cwd(), "..");
// Docker wants forward slashes, and no shell in between, or a Windows path with a space in
// it arrives as something else entirely.
const MOUNT = `${OUT_DIR.split(sep).join("/")}:/fx`;

/** Runs one binary from the backend image against the fixtures directory. */
function inBackend(entrypoint, args) {
  const result = spawnSync(
    "docker",
    ["compose", "run", "--rm", "--entrypoint", entrypoint, "-v", MOUNT, "backend", ...args],
    { cwd: REPO_ROOT, stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" },
  );
  if (result.error) throw new Error(`could not run docker: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(`${entrypoint} failed (${result.status}): ${result.stderr || result.stdout}`);
  }
}

/** A6-ish page, small enough that the fixtures stay a few KB. */
const WIDTH = 420;
const HEIGHT = 595;

async function makeTextPdf() {
  const pdf = await PDFDocument.create();
  pdf.setTitle("PDFKit sample document");
  const font = await pdf.embedFont(StandardFonts.Helvetica);
  const bold = await pdf.embedFont(StandardFonts.HelveticaBold);

  const sections = [
    "Quarterly summary",
    "Regional breakdown",
    "Open questions",
    "Appendix: method",
    "Appendix: raw figures",
  ];

  sections.forEach((heading, index) => {
    const page = pdf.addPage([WIDTH, HEIGHT]);
    page.drawRectangle({
      x: 0,
      y: HEIGHT - 70,
      width: WIDTH,
      height: 70,
      color: rgb(0.09, 0.32, 0.36),
    });
    page.drawText(heading, {
      x: 36,
      y: HEIGHT - 45,
      size: 16,
      font: bold,
      color: rgb(1, 1, 1),
    });
    page.drawText(`Page ${index + 1} of ${sections.length}`, {
      x: 36,
      y: HEIGHT - 110,
      size: 11,
      font,
      color: rgb(0.2, 0.2, 0.2),
    });
    for (let line = 0; line < 12; line += 1) {
      page.drawText(
        "Selectable text so OCR and text extraction have something to find.",
        { x: 36, y: HEIGHT - 140 - line * 18, size: 9, font, color: rgb(0.35, 0.35, 0.35) },
      );
    }
  });

  await writeFile(join(OUT_DIR, "sample-text.pdf"), await pdf.save());
  return "sample-text.pdf";
}

/**
 * Pages whose only content is a bitmap, so they have no extractable text. This is the OCR
 * and "extract images" fixture, and the one Compress is measured on.
 *
 * The bitmap is a real render of the text fixture rather than drawn shapes: OCR can
 * only be verified against something that genuinely says words, and Ghostscript can only
 * show a difference between compression levels on something that genuinely has raster data
 * to throw away.
 */
async function makeScannedPdf() {
  // 300 dpi, not 150: Compress maps its three levels to 72 / 150 / 300 dpi, so a source at
  // 150 leaves the top two levels with nothing to downsample and all three come back the
  // same size.
  inBackend("pdftoppm", ["-r", "300", "-png", "-f", "1", "-l", "2", "/fx/sample-text.pdf", "/fx/.scan"]);

  const pdf = await PDFDocument.create();
  pdf.setTitle("PDFKit scanned sample");

  for (const index of [1, 2]) {
    const source = join(OUT_DIR, `.scan-${index}.png`);
    const png = await pdf.embedPng(await readFile(source));
    const page = pdf.addPage([WIDTH, HEIGHT]);
    page.drawImage(png, { x: 0, y: 0, width: WIDTH, height: HEIGHT });
    await rm(source);
  }

  await writeFile(join(OUT_DIR, "sample-scanned.pdf"), await pdf.save());
  return "sample-scanned.pdf";
}

/** The same document as sample-text.pdf, behind the password "hunter2". */
function makeProtectedPdf() {
  inBackend("qpdf", [
    "--encrypt", "hunter2", "hunter2", "256", "--",
    "/fx/sample-text.pdf", "/fx/sample-protected.pdf",
  ]);
  return "sample-protected.pdf";
}

await mkdir(OUT_DIR, { recursive: true });
// Order matters: the other two are made out of the text one.
const written = [await makeTextPdf(), await makeScannedPdf(), makeProtectedPdf()];
console.log(`[fixtures] wrote ${written.join(", ")} to test-fixtures/`);
console.log('[fixtures] sample-protected.pdf opens with the password "hunter2".');
