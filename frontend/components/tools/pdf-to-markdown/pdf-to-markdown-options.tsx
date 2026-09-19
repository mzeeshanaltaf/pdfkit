"use client";

import { FileCode } from "lucide-react";

import { OcrLanguagePicker } from "@/components/tool/ocr-language-picker";
import { OcrModeCards, type OcrMode } from "@/components/tool/ocr-mode-cards";
import { useToolShell } from "@/components/tool/tool-shell-context";
import { useScannedProbe } from "@/components/tool/use-scanned-probe";
import { useOcrLanguages } from "@/components/tool/use-ocr-languages";
import { formatBytes } from "@/lib/format";

export interface MarkdownState {
  mode: OcrMode;
  languages: string[];
}

/**
 * OCR is on by default here, unlike PDF to Word. The converter refuses a page it cannot
 * read outright, so defaulting this off would turn the commonest scanned document into an
 * error instead of a result.
 */
export function createMarkdownState(): MarkdownState {
  return { mode: "auto", languages: ["eng"] };
}

/** The CTA gate, shared by the panel and ToolShell's `canSubmit`. */
export function markdownReady(state: MarkdownState): boolean {
  return state.mode === "off" || state.languages.length > 0;
}

interface PdfToMarkdownOptionsProps {
  state: MarkdownState;
  onChange: (next: MarkdownState) => void;
}

export function PdfToMarkdownOptions({ state, onChange }: PdfToMarkdownOptionsProps) {
  const { files } = useToolShell();
  const { languages, loading } = useOcrLanguages();
  const { scanned } = useScannedProbe(files);

  const readable = files.filter((file) => !file.error);
  const totalSize = readable.reduce((sum, file) => sum + file.size, 0);
  const set = (patch: Partial<MarkdownState>) => onChange({ ...state, ...patch });

  return (
    <div className="space-y-6">
      <OcrModeCards
        mode={state.mode}
        onChange={(mode) => set({ mode })}
        scannedCount={scanned.length}
        offDescription="Convert only the pages that already have text. A scanned page stops the conversion."
        onDescription="Read scanned pages with OCR and fold their text into the document. Recommended."
      />

      {state.mode === "auto" && (
        <div className="border-t border-border pt-5">
          <OcrLanguagePicker
            languages={languages}
            loading={loading}
            selected={state.languages}
            onChange={(codes) => set({ languages: codes })}
          />
        </div>
      )}

      <div className="flex gap-2.5 rounded-lg border border-border bg-muted/50 p-3.5 text-sm leading-relaxed">
        <FileCode className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <p>
          Headings, lists and tables carry over as Markdown. Fonts, colours and exact
          spacing do not, which is rather the point of Markdown.
        </p>
      </div>

      {readable.length > 0 && (
        <p className="border-t border-border pt-5 text-sm text-muted-foreground">
          {readable.length === 1 ? "1 file" : `${readable.length} files`},{" "}
          <span className="font-medium text-foreground">{formatBytes(totalSize)}</span> to
          upload.
          {readable.length > 1 && " They come back as a ZIP."}
        </p>
      )}
    </div>
  );
}
