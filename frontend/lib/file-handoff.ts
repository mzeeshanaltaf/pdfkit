/**
 * Hands a File from one tool's workspace to another across a client-side navigation.
 *
 * This is what makes the encrypted-PDF banner's "Go to Unlock PDF" button useful: without
 * it the user arrives at Unlock and has to find the same file again. A module-level slot is
 * enough because a `next/link` navigation keeps the JS context alive; a full page load
 * clears it, which is correct — the File objects would be gone by then anyway.
 */

let pending: File[] = [];

export function handOffFiles(files: File[]): void {
  pending = files;
}

/** Returns the handed-over files and empties the slot, so they are adopted exactly once. */
export function takeHandedOffFiles(): File[] {
  const files = pending;
  pending = [];
  return files;
}
