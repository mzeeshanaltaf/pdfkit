"use client";

import { FileText } from "lucide-react";

import { OcrLanguagePicker } from "@/components/tool/ocr-language-picker";
import { OcrModeCards, type OcrMode } from "@/components/tool/ocr-mode-cards";
import { useToolShell } from "@/components/tool/tool-shell-context";
import { useScannedProbe } from "@/components/tool/use-scanned-probe";
import { useOcrLanguages } from "@/components/tool/use-ocr-languages";
import { formatBytes } from "@/lib/format";

export interface WordState {
  mode: OcrMode;
  languages: string[];
}

/** No OCR by default: pdf2docx produces a document either way, and OCR costs real time. */
export function createWordState(): WordState {
  return { mode: "off", languages: ["eng"] };
}

/** The CTA gate, shared by the panel and ToolShell's `canSubmit`. */
export function wordReady(state: WordState): boolean {
  return state.mode === "off" || state.languages.length > 0;
}

interface PdfToWordOptionsProps {
  state: WordState;
  onChange: (next: WordState) => void;
}

export function PdfToWordOptions({ state, onChange }: PdfToWordOptionsProps) {
  const { files } = useToolShell();
  const { languages, loading } = useOcrLanguages();
  const { scanned } = useScannedProbe(files);

  const readable = files.filter((file) => !file.error);
  const totalSize = readable.reduce((sum, file) => sum + file.size, 0);
  const set = (patch: Partial<WordState>) => onChange({ ...state, ...patch });

  return (
    <div className="space-y-6">
      <OcrModeCards
        mode={state.mode}
        onChange={(mode) => set({ mode })}
        scannedCount={scanned.length}
        offDescription="Convert a PDF whose text you can already select into an editable Word file."
        onDescription="Read scanned pages first, so their words end up as editable text rather than a picture."
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
        <FileText className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <p>
          Paragraphs, tables and images are rebuilt as real Word content, so the result is
          editable. A heavily designed page comes out approximately rather than exactly.
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
