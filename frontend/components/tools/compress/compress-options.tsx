"use client";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { formatBytes } from "@/lib/format";

/** Mirrors the backend's Ghostscript presets in `app/services/compress.py`. */
export type CompressLevel = "extreme" | "recommended" | "less";

export const DEFAULT_COMPRESS_LEVEL: CompressLevel = "recommended";

interface LevelChoice {
  value: CompressLevel;
  label: string;
  quality: string;
  description: string;
}

/** Ordered smallest file first, which is also how iLovePDF stacks them. */
const LEVELS: LevelChoice[] = [
  {
    value: "extreme",
    label: "Extreme compression",
    quality: "Less quality, high compression",
    description: "Images drop to 72 dpi. Good for email and forms, not for print.",
  },
  {
    value: "recommended",
    label: "Recommended compression",
    quality: "Good quality, good compression",
    description: "Images drop to 150 dpi. Still sharp on screen at full size.",
  },
  {
    value: "less",
    label: "Less compression",
    quality: "High quality, less compression",
    description: "Images stay at 300 dpi, so the document is still print-ready.",
  },
];

interface CompressOptionsProps {
  level: CompressLevel;
  onChange: (level: CompressLevel) => void;
}

export function CompressOptions({ level, onChange }: CompressOptionsProps) {
  const { files } = useToolShell();
  const readable = files.filter((file) => !file.error);
  const totalSize = readable.reduce((sum, file) => sum + file.size, 0);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-medium">Compression level</h2>
        <RadioGroup
          className="mt-3 grid gap-3"
          value={level}
          onValueChange={(value) => onChange(value as CompressLevel)}
        >
          {LEVELS.map((choice) => (
            <Label
              key={choice.value}
              htmlFor={`compress-${choice.value}`}
              data-selected={level === choice.value || undefined}
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-sm font-normal transition-colors hover:border-brand/50 data-selected:border-brand data-selected:bg-brand/8"
            >
              <RadioGroupItem id={`compress-${choice.value}`} value={choice.value} className="mt-0.5" />
              <span className="min-w-0">
                <span className="block font-medium">{choice.label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{choice.quality}</span>
                <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                  {choice.description}
                </span>
              </span>
            </Label>
          ))}
        </RadioGroup>
      </section>

      {readable.length > 0 && (
        <p className="border-t border-border pt-5 text-sm text-muted-foreground">
          {readable.length === 1 ? "1 file" : `${readable.length} files`},{" "}
          <span className="font-medium text-foreground">{formatBytes(totalSize)}</span> to upload.
          {readable.length > 1 && " They come back as a ZIP."}
        </p>
      )}
    </div>
  );
}
