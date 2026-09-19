"use client";

import { useEffect, useRef, useState } from "react";

import { probeTextLayer } from "@/lib/pdf/text-layer";

import type { ToolFile } from "./types";

export interface ScannedProbe {
  /** Files whose sampled pages had no text layer — the ones OCR would help. */
  scanned: string[];
  /** True until every readable file in the list has been looked at. */
  loading: boolean;
}

/**
 * Which of the loaded files look like scans.
 *
 * Drives the "some of these pages are scanned" hint on the conversion tools,
 * which is the difference between someone getting an empty Word document and
 * understanding why. The answer is a property of the File and never changes, so
 * results are remembered by id and a file is only ever probed once.
 */
export function useScannedProbe(files: ToolFile[]): ScannedProbe {
  const [results, setResults] = useState<Record<string, boolean>>({});
  const started = useRef(new Set<string>());
  const mounted = useRef(true);

  // Only unmounting invalidates a probe in flight. Tying that to the effect
  // below instead would drop every result: `files` gets a new identity the
  // moment a page count or thumbnail arrives, so the effect re-runs while the
  // first probe is still going, and a file already in `started` is never
  // probed again — the answer would be discarded and never recomputed.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    for (const file of files) {
      if (file.error || started.current.has(file.id)) continue;
      started.current.add(file.id);

      probeTextLayer(file.file)
        .then(({ checked, scanned }) => {
          if (!mounted.current) return;
          // Every page we looked at was blank, so the rest almost certainly are
          // too. A document with even one readable page is not a scan.
          setResults((current) => ({
            ...current,
            [file.id]: checked > 0 && scanned === checked,
          }));
        })
        .catch(() => {
          // A file pdf.js cannot read is already flagged on its own card by the
          // shell; there is nothing useful to say about its text layer.
          if (mounted.current) {
            setResults((current) => ({ ...current, [file.id]: false }));
          }
        });
    }
  }, [files]);

  const readable = files.filter((file) => !file.error);
  return {
    scanned: readable.filter((file) => results[file.id]).map((file) => file.id),
    loading: readable.some((file) => !(file.id in results)),
  };
}
