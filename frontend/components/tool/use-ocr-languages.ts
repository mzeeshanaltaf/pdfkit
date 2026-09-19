"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { getJson } from "@/lib/api";

export interface OcrLanguage {
  code: string;
  name: string;
}

/** The backend's own default, and the only model the image is guaranteed to ship. */
export const FALLBACK_LANGUAGES: OcrLanguage[] = [{ code: "eng", name: "English" }];

export interface OcrLanguagesState {
  languages: OcrLanguage[];
  loading: boolean;
}

/**
 * The installed Tesseract models, read from the server at page load.
 *
 * Which languages exist is a property of the backend image, not of this app, so hardcoding
 * a list here would go stale the moment a model is added to the Dockerfile. If the call
 * fails the picker falls back to English rather than blocking the tool — the backend
 * defaults to English anyway when the field is empty.
 */
export function useOcrLanguages(): OcrLanguagesState {
  const [languages, setLanguages] = useState<OcrLanguage[]>(FALLBACK_LANGUAGES);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    getJson<OcrLanguage[]>("/ocr/languages", controller.signal)
      .then((installed) => {
        if (installed.length > 0) setLanguages(installed);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        toast.error("Could not load the OCR language list. Falling back to English.");
        console.error(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, []);

  return { languages, loading };
}
