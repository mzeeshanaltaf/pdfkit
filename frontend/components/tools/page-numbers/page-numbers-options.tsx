"use client";

import { AlertCircle, Bold, Italic, Underline } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  FontFamily,
  HorizontalPosition,
  MarginSize,
  VerticalPosition,
} from "@/lib/pdf/pageNumbers";
import { cn } from "@/lib/utils";

import {
  FONT_LABELS,
  MARGIN_LABELS,
  planFromState,
  previewFile,
  TEMPLATE_PRESETS,
  TEXT_SIZES,
  type PageNumbersState,
  type TemplateId,
} from "./page-numbers-state";

interface PageNumbersOptionsProps {
  state: PageNumbersState;
  onChange: (next: PageNumbersState) => void;
}

const VERTICALS: VerticalPosition[] = ["top", "middle", "bottom"];
const HORIZONTALS: HorizontalPosition[] = ["left", "center", "right"];

export function PageNumbersOptions({ state, onChange }: PageNumbersOptionsProps) {
  const { files } = useToolShell();
  const readable = files.filter((file) => !file.error);
  // The range is checked against the file on screen; other files are clamped when stamped.
  const previewPageCount = previewFile(files, state.previewFileId)?.pageCount ?? null;
  const { plan, issue } = planFromState(state, previewPageCount);

  const set = (patch: Partial<PageNumbersState>) => onChange({ ...state, ...patch });

  return (
    <div className="space-y-6">
      {readable.length > 1 && (
        <section>
          <Label htmlFor="numbers-preview-file" className="text-xs">
            Previewing
          </Label>
          <Select
            value={state.previewFileId ?? readable[0].id}
            onValueChange={(value) => set({ previewFileId: value })}
          >
            <SelectTrigger id="numbers-preview-file" className="mt-1.5 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {readable.map((file) => (
                <SelectItem key={file.id} value={file.id}>
                  {file.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="mt-1.5 text-xs text-muted-foreground">
            The same settings are applied to all {readable.length} files.
          </p>
        </section>
      )}

      <section>
        <h2 className="text-sm font-medium">Position</h2>
        <div className="mt-3 grid grid-cols-[auto_1fr] gap-4">
          <div
            role="radiogroup"
            aria-label="Where the number goes on the page"
            className="grid w-fit grid-cols-3 gap-1 rounded-lg border border-border bg-muted/40 p-1"
          >
            {VERTICALS.map((vertical) =>
              HORIZONTALS.map((horizontal) => {
                const selected =
                  state.position.vertical === vertical &&
                  state.position.horizontal === horizontal;
                return (
                  <button
                    key={`${vertical}-${horizontal}`}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-label={`${vertical} ${horizontal}`}
                    onClick={() => set({ position: { vertical, horizontal } })}
                    className={cn(
                      "flex size-8 cursor-pointer items-center justify-center rounded-md border border-transparent bg-background transition-colors hover:border-brand/40",
                      selected && "border-brand bg-brand/10",
                    )}
                  >
                    <span
                      className={cn(
                        "size-1.5 rounded-full",
                        selected ? "bg-brand" : "bg-muted-foreground/40",
                      )}
                      aria-hidden
                    />
                  </button>
                );
              }),
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="numbers-margin" className="text-xs">
              Margin
            </Label>
            <Select
              value={state.margin}
              onValueChange={(value) => set({ margin: value as MarginSize })}
            >
              <SelectTrigger id="numbers-margin" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(MARGIN_LABELS) as MarginSize[]).map((margin) => (
                  <SelectItem key={margin} value={margin}>
                    {MARGIN_LABELS[margin]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-3">
          <ModeCard
            label="Single page"
            hint="Same spot on every page"
            selected={state.mode === "single"}
            onSelect={() => set({ mode: "single" })}
          />
          <ModeCard
            label="Facing pages"
            hint="Mirrored on even pages"
            selected={state.mode === "facing"}
            onSelect={() => set({ mode: "facing" })}
          />
        </div>
      </section>

      <section className="space-y-3 border-t border-border pt-5">
        <h2 className="text-sm font-medium">Numbering</h2>
        <div className="grid grid-cols-3 gap-3">
          <Field
            id="numbers-from"
            label="From page"
            value={state.fromPage}
            placeholder="1"
            max={previewPageCount}
            onChange={(fromPage) => set({ fromPage })}
          />
          <Field
            id="numbers-to"
            label="To page"
            value={state.toPage}
            placeholder={previewPageCount === null ? "last" : String(previewPageCount)}
            max={previewPageCount}
            onChange={(toPage) => set({ toPage })}
          />
          <Field
            id="numbers-first"
            label="Start at"
            value={state.firstNumber}
            placeholder="1"
            onChange={(firstNumber) => set({ firstNumber })}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="numbers-template" className="text-xs">
            Text
          </Label>
          <Select
            value={state.templateId}
            onValueChange={(value) => set({ templateId: value as TemplateId })}
          >
            <SelectTrigger id="numbers-template" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TEMPLATE_PRESETS.map((preset) => (
                <SelectItem key={preset.id} value={preset.id}>
                  {preset.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {state.templateId === "custom" && (
          <div className="space-y-1.5">
            <Input
              aria-label="Custom page number text"
              placeholder="Page {n} of {N}"
              autoComplete="off"
              value={state.customTemplate}
              onChange={(event) => set({ customTemplate: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              <code>{"{n}"}</code> is the page&apos;s number, <code>{"{N}"}</code> the last one.
            </p>
          </div>
        )}
      </section>

      <section className="space-y-3 border-t border-border pt-5">
        <h2 className="text-sm font-medium">Text style</h2>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="numbers-font" className="text-xs">
              Font
            </Label>
            <Select
              value={state.font}
              onValueChange={(value) => set({ font: value as FontFamily })}
            >
              <SelectTrigger id="numbers-font" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(FONT_LABELS) as FontFamily[]).map((font) => (
                  <SelectItem key={font} value={font}>
                    {FONT_LABELS[font]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="numbers-size" className="text-xs">
              Size
            </Label>
            <Select
              value={String(state.size)}
              onValueChange={(value) => set({ size: Number(value) })}
            >
              <SelectTrigger id="numbers-size" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TEXT_SIZES.map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size} pt
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <StyleToggle
              label="Bold"
              icon={Bold}
              pressed={state.bold}
              onToggle={() => set({ bold: !state.bold })}
            />
            <StyleToggle
              label="Italic"
              icon={Italic}
              pressed={state.italic}
              onToggle={() => set({ italic: !state.italic })}
            />
            <StyleToggle
              label="Underline"
              icon={Underline}
              pressed={state.underline}
              onToggle={() => set({ underline: !state.underline })}
            />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Label htmlFor="numbers-color" className="text-xs">
              Colour
            </Label>
            <input
              id="numbers-color"
              type="color"
              value={state.color}
              onChange={(event) => set({ color: event.target.value })}
              className="size-9 cursor-pointer rounded-lg border border-border bg-background p-1"
            />
          </div>
        </div>
      </section>

      {issue ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {issue}
        </p>
      ) : (
        plan && (
          <p className="text-sm text-muted-foreground">
            {plan.pages.length === 1 ? "One page gets" : `${plan.pages.length} pages get`} a
            number, starting at{" "}
            <span className="font-medium text-foreground">{plan.pages[0]?.text}</span>.
          </p>
        )
      )}
    </div>
  );
}

interface FieldProps {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  max?: number | null;
  onChange: (value: string) => void;
}

function Field({ id, label, value, placeholder, max, onChange }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        min={1}
        max={max ?? undefined}
        inputMode="numeric"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function ModeCard({
  label,
  hint,
  selected,
  onSelect,
}: {
  label: string;
  hint: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "cursor-pointer rounded-lg border border-border p-3 text-left transition-colors hover:border-brand/50",
        selected && "border-brand bg-brand/8",
      )}
    >
      <span className="block text-sm font-medium">{label}</span>
      <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}

function StyleToggle({
  label,
  icon: Icon,
  pressed,
  onToggle,
}: {
  label: string;
  icon: React.ComponentType<{ "aria-hidden"?: boolean }>;
  pressed: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      variant="outline"
      size="icon-lg"
      aria-label={label}
      aria-pressed={pressed}
      onClick={onToggle}
      className={cn(pressed && "border-brand bg-brand/10 text-brand")}
    >
      <Icon aria-hidden />
    </Button>
  );
}
