"use client";

import { ScanText } from "lucide-react";

import { OcrLanguagePicker } from "@/components/tool/ocr-language-picker";
import type { OcrLanguage } from "@/components/tool/use-ocr-languages";

export { MAX_LANGUAGES } from "@/components/tool/ocr-language-picker";

interface OcrOptionsProps {
  languages: OcrLanguage[];
  loading: boolean;
  selected: string[];
  onChange: (codes: string[]) => void;
}

export function OcrOptions({ languages, loading, selected, onChange }: OcrOptionsProps) {
  return (
    <div className="space-y-6">
      <OcrLanguagePicker
        languages={languages}
        loading={loading}
        selected={selected}
        onChange={onChange}
      />

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
