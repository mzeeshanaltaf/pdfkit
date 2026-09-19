"use client";

import { Images, ScanLine } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { JPG_QUALITIES, type JpgQuality } from "@/lib/pdf/pdfToJpg";
import { cn } from "@/lib/utils";

export type JpgMode = "pages" | "extract";

export interface JpgState {
  mode: JpgMode;
  quality: JpgQuality;
}

export function createJpgState(): JpgState {
  return { mode: "pages", quality: "normal" };
}

interface PdfToJpgOptionsProps {
  state: JpgState;
  onChange: (next: JpgState) => void;
}

export function PdfToJpgOptions({ state, onChange }: PdfToJpgOptionsProps) {
  const { files } = useToolShell();
  const readable = files.filter((file) => !file.error);
  const counted = readable.every((file) => file.pageCount !== null);
  const pages = readable.reduce((sum, file) => sum + (file.pageCount ?? 0), 0);

  const set = (patch: Partial<JpgState>) => onChange({ ...state, ...patch });

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-medium">What to convert</h2>
        <div className="mt-3 grid gap-3">
          <ModeCard
            icon={ScanLine}
            title="Page to JPG"
            description={
              counted
                ? `${pages} ${pages === 1 ? "JPG" : "JPGs"} will be created, one per page.`
                : "One JPG per page, rendered in your browser."
            }
            selected={state.mode === "pages"}
            onSelect={() => set({ mode: "pages" })}
          />
          <ModeCard
            icon={Images}
            title="Extract images"
            description="Pull out the photos already embedded in the document."
            selected={false}
            // Extracting embedded images means reading the document's image streams, which
            // is a backend job; the mode is shown now so the choice is not a surprise later.
            comingSoon
          />
        </div>
      </section>

      <section className="border-t border-border pt-5">
        <h2 className="text-sm font-medium">Quality</h2>
        <RadioGroup
          className="mt-3 grid grid-cols-2 gap-3"
          value={state.quality}
          onValueChange={(value) => set({ quality: value as JpgQuality })}
        >
          {(Object.keys(JPG_QUALITIES) as JpgQuality[]).map((quality) => (
            <Label
              key={quality}
              htmlFor={`jpg-quality-${quality}`}
              data-selected={state.quality === quality || undefined}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-border p-3 text-sm font-normal transition-colors data-selected:border-brand data-selected:bg-brand/8"
            >
              <RadioGroupItem id={`jpg-quality-${quality}`} value={quality} />
              <span>
                {JPG_QUALITIES[quality].label}
                <span className="block text-xs text-muted-foreground">
                  ≈{JPG_QUALITIES[quality].dpi} dpi
                </span>
              </span>
            </Label>
          ))}
        </RadioGroup>
        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          Normal is sized for the screen. High is worth it for printing or for reading small
          type, and makes files roughly twice as large.
        </p>
      </section>

      {pages > 1 && (
        <p className="border-t border-border pt-5 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{pages} JPGs</span>, delivered as a ZIP.
        </p>
      )}
    </div>
  );
}

interface ModeCardProps {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  description: string;
  selected: boolean;
  onSelect?: () => void;
  comingSoon?: boolean;
}

/** A mode as a pressable card, so the whole box — icon, title and blurb — is the hit target. */
function ModeCard({
  icon: Icon,
  title,
  description,
  selected,
  onSelect,
  comingSoon = false,
}: ModeCardProps) {
  return (
    <button
      type="button"
      disabled={comingSoon}
      aria-pressed={comingSoon ? undefined : selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border border-border p-3 text-left transition-colors",
        selected && "border-brand bg-brand/8",
        comingSoon ? "opacity-60" : "cursor-pointer hover:border-brand/50",
      )}
    >
      <Icon className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden />
      <span className="min-w-0">
        <span className="flex items-center gap-2 text-sm font-medium">
          {title}
          {comingSoon && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              Coming soon
            </span>
          )}
        </span>
        <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  );
}
