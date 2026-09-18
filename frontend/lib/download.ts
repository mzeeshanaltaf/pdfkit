import { saveAs } from "file-saver";

/** Saves a processed blob to the user's downloads folder. */
export function downloadBlob(blob: Blob, filename: string): void {
  saveAs(blob, filename);
}
