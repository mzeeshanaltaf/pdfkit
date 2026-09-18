/**
 * Generates the PDFs used to verify the UI by hand, in frontend/test-fixtures/.
 *
 * They are committed and reused from phase 1 through phase 6, so this only needs running
 * again if a fixture is lost or a new one is needed:
 *
 *   node scripts/make-test-fixtures.mjs
 *
 * The encrypted fixture needs qpdf, which is not installed locally, so it is produced from
 * the backend image (see the command printed at the end).
 */
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { crc32, deflateSync } from "node:zlib";

import { PDFDocument, StandardFonts, rgb } from "pdf-lib";

const OUT_DIR = join(process.cwd(), "test-fixtures");

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
 * A page whose only content is a bitmap, so it has no extractable text. This is the OCR
 * and "extract images" fixture.
 */
async function makeScannedPdf() {
  const pdf = await PDFDocument.create();
  pdf.setTitle("PDFKit scanned sample");

  const png = await pdf.embedPng(buildWordPng());
  for (let index = 0; index < 2; index += 1) {
    const page = pdf.addPage([WIDTH, HEIGHT]);
    page.drawImage(png, { x: 40, y: HEIGHT - 220, width: WIDTH - 80, height: 160 });
  }

  await writeFile(join(OUT_DIR, "sample-scanned.pdf"), await pdf.save());
  return "sample-scanned.pdf";
}

/** Minimal uncompressed-ish PNG writer: enough to embed a legible block of "ink". */
function buildWordPng() {
  const width = 240;
  const height = 80;
  const pixels = Buffer.alloc(height * (1 + width * 3), 0xff);

  // Row filter byte is 0 for every row; the rest is RGB.
  for (let y = 0; y < height; y += 1) {
    const rowStart = y * (1 + width * 3);
    pixels[rowStart] = 0;
    for (let x = 0; x < width; x += 1) {
      // Five thick vertical strokes reading as a word-shaped smudge to a person,
      // and as an image with no text layer to a PDF parser.
      const inStroke = y > 18 && y < 62 && Math.floor(x / 12) % 4 === 0 && x > 20 && x < 220;
      const offset = rowStart + 1 + x * 3;
      const value = inStroke ? 0x18 : 0xff;
      pixels[offset] = value;
      pixels[offset + 1] = value;
      pixels[offset + 2] = value;
    }
  }

  const chunks = [
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", ihdr(width, height)),
    pngChunk("IDAT", deflateSync(pixels)),
    pngChunk("IEND", Buffer.alloc(0)),
  ];
  return Buffer.concat(chunks);
}

function ihdr(width, height) {
  const buffer = Buffer.alloc(13);
  buffer.writeUInt32BE(width, 0);
  buffer.writeUInt32BE(height, 4);
  buffer[8] = 8; // bit depth
  buffer[9] = 2; // colour type: truecolour
  return buffer;
}

function pngChunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeAndData = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData) >>> 0, 0);
  return Buffer.concat([length, typeAndData, crc]);
}

await mkdir(OUT_DIR, { recursive: true });
const written = [await makeTextPdf(), await makeScannedPdf()];
console.log(`[fixtures] wrote ${written.join(", ")} to test-fixtures/`);
console.log(
  "[fixtures] for sample-protected.pdf run qpdf from the backend image:\n" +
    "  docker compose run --rm --entrypoint qpdf -v \"$PWD/frontend/test-fixtures:/fx\" backend \\\n" +
    "    --encrypt hunter2 hunter2 256 -- /fx/sample-text.pdf /fx/sample-protected.pdf",
);
