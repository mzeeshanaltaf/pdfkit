"use client";

import { Languages, ScanText } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

import type { OcrLanguage } from "./use-ocr-languages";

/** Mirrors the backend's MAX_OCR_LANGUAGES — each extra language costs a full pass. */
export const MAX_LANGUAGES = 3;

interface OcrOptionsProps {
  languages: OcrLanguage[];
  loading: boolean;
  selected: string[];
  onChange: (codes: string[]) => void;
}

export function OcrOptions({ languages, loading, selected, onChange }: OcrOptionsProps) {
  const full = selected.length >= MAX_LANGUAGES;

  const toggle = (code: string) => {
    if (selected.includes(code)) {
      onChange(selected.filter((entry) => entry !== code));
      return;
    }
    if (full) return;
    // Order matters downstream: Tesseract weights the first language most heavily.
    onChange([...selected, code]);
  };

  return (
    <div className="space-y-6">
      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="flex items-center gap-2 text-sm font-medium">
            <Languages className="size-4 text-brand" aria-hidden />
            Document language
          </h2>
          <span className="text-xs text-muted-foreground">
            {selected.length} of {MAX_LANGUAGES}
          </span>
        </div>

        {loading ? (
          <div className="mt-3 space-y-2" aria-hidden>
            {[0, 1, 2].map((row) => (
              <div key={row} className="h-10 animate-pulse rounded-lg bg-muted" />
            ))}
            <span className="sr-only">Loading the available languages</span>
          </div>
        ) : (
          <ul className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
            {languages.map((language) => {
              const checked = selected.includes(language.code);
              return (
                <li key={language.code}>
                  <Label
                    htmlFor={`ocr-lang-${language.code}`}
                    data-selected={checked || undefined}
                    className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-2.5 text-sm font-normal transition-colors hover:border-brand/50 has-disabled:cursor-not-allowed has-disabled:opacity-50 data-selected:border-brand data-selected:bg-brand/8"
                  >
                    <Checkbox
                      id={`ocr-lang-${language.code}`}
                      checked={checked}
                      disabled={!checked && full}
                      onCheckedChange={() => toggle(language.code)}
                    />
                    <span className="min-w-0 flex-1 truncate">{language.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {language.code}
                    </span>
                  </Label>
                </li>
              );
            })}
          </ul>
        )}

        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          {selected.length === 0
            ? "Pick at least one language — OCR has to know what it is reading."
            : `Pick up to ${MAX_LANGUAGES}. Choosing more languages than the document actually uses makes the result worse, not better — the first one you pick counts for most.`}
        </p>
      </section>

      <div className="flex gap-2.5 rounded-lg border border-border bg-muted/50 p-3.5 text-sm leading-relaxed">
        <ScanText className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <p>
          OCR reads the page as an image and guesses the text, so a clean 300 dpi scan comes
          out near-perfect while a photographed or faint page will not. Pages that already
          have real text are left exactly as they are.
        </p>
      </div>
    </div>
  );
}
