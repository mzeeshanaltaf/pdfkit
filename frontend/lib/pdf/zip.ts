import JSZip from "jszip";

export interface ZipEntry {
  name: string;
  blob: Blob;
}

/**
 * Bundles the outputs of a tool that produced more than one file.
 *
 * PDFs are already compressed internally, so level 1 is deliberate: it still squeezes the
 * uncompressed object streams pdf-lib writes, without spending seconds of main-thread time
 * deflating image data that will not shrink.
 */
export async function zipBlobs(entries: ZipEntry[]): Promise<Blob> {
  const zip = new JSZip();
  const used = new Set<string>();

  for (const entry of entries) {
    zip.file(uniqueName(entry.name, used), entry.blob);
  }

  return zip.generateAsync({
    type: "blob",
    compression: "DEFLATE",
    compressionOptions: { level: 1 },
  });
}

/** Two source files can share a name; a zip entry silently overwrites, so disambiguate. */
function uniqueName(name: string, used: Set<string>): string {
  if (!used.has(name)) {
    used.add(name);
    return name;
  }

  const dot = name.lastIndexOf(".");
  const base = dot === -1 ? name : name.slice(0, dot);
  const extension = dot === -1 ? "" : name.slice(dot);

  let counter = 2;
  let candidate = `${base} (${counter})${extension}`;
  while (used.has(candidate)) {
    counter += 1;
    candidate = `${base} (${counter})${extension}`;
  }

  used.add(candidate);
  return candidate;
}
