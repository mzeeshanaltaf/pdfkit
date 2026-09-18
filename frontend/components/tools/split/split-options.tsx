"use client";

import { AlertCircle, Plus, X } from "lucide-react";

import { useToolShell } from "@/components/tool/tool-shell-context";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatPageCount } from "@/lib/format";
import type { SplitChunk } from "@/lib/pdf/split";

import {
  newRangeRow,
  planFromState,
  type PagesMode,
  type RangeMode,
  type SplitState,
  type SplitTab,
} from "./split-state";

interface SplitOptionsProps {
  state: SplitState;
  onChange: (next: SplitState) => void;
}

export function SplitOptions({ state, onChange }: SplitOptionsProps) {
  const { files } = useToolShell();
  const pageCount = files.find((file) => !file.error)?.pageCount ?? null;
  const { chunks, issue } = planFromState(state, pageCount);

  const set = (patch: Partial<SplitState>) => onChange({ ...state, ...patch });

  const updateRange = (id: string, patch: { from?: string; to?: string }) =>
    set({ ranges: state.ranges.map((row) => (row.id === id ? { ...row, ...patch } : row)) });

  return (
    <div className="space-y-6">
      <Tabs value={state.tab} onValueChange={(value) => set({ tab: value as SplitTab })}>
        <TabsList className="w-full">
          <TabsTrigger value="range" className="flex-1">
            Range
          </TabsTrigger>
          <TabsTrigger value="pages" className="flex-1">
            Pages
          </TabsTrigger>
        </TabsList>

        <TabsContent value="range" className="mt-5 space-y-5">
          <RadioGroup
            className="grid grid-cols-2 gap-3"
            value={state.rangeMode}
            onValueChange={(value) => set({ rangeMode: value as RangeMode })}
          >
            <ModeCard value="custom" current={state.rangeMode} label="Custom ranges" />
            <ModeCard value="fixed" current={state.rangeMode} label="Fixed ranges" />
          </RadioGroup>

          {state.rangeMode === "custom" ? (
            <div className="space-y-3">
              {state.ranges.map((row, index) => (
                <div key={row.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      Range {index + 1}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Remove range ${index + 1}`}
                      disabled={state.ranges.length === 1}
                      onClick={() =>
                        set({ ranges: state.ranges.filter((entry) => entry.id !== row.id) })
                      }
                    >
                      <X aria-hidden />
                    </Button>
                  </div>

                  <div className="mt-2 grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor={`${row.id}-from`} className="text-xs">
                        From page
                      </Label>
                      <Input
                        id={`${row.id}-from`}
                        type="number"
                        min={1}
                        max={pageCount ?? undefined}
                        inputMode="numeric"
                        placeholder="1"
                        value={row.from}
                        onChange={(event) => updateRange(row.id, { from: event.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`${row.id}-to`} className="text-xs">
                        To page
                      </Label>
                      <Input
                        id={`${row.id}-to`}
                        type="number"
                        min={1}
                        max={pageCount ?? undefined}
                        inputMode="numeric"
                        placeholder={pageCount === null ? "last" : String(pageCount)}
                        value={row.to}
                        onChange={(event) => updateRange(row.id, { to: event.target.value })}
                      />
                    </div>
                  </div>
                </div>
              ))}

              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => set({ ranges: [...state.ranges, newRangeRow()] })}
              >
                <Plus aria-hidden />
                Add range
              </Button>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="split-every" className="text-xs">
                Split every
              </Label>
              <div className="flex items-center gap-2.5">
                <Input
                  id="split-every"
                  type="number"
                  min={1}
                  max={pageCount ?? undefined}
                  inputMode="numeric"
                  className="w-24"
                  value={state.every}
                  onChange={(event) => set({ every: event.target.value })}
                />
                <span className="text-sm text-muted-foreground">pages</span>
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="pages" className="mt-5 space-y-5">
          <RadioGroup
            className="grid grid-cols-2 gap-3"
            value={state.pagesMode}
            onValueChange={(value) => set({ pagesMode: value as PagesMode })}
          >
            <ModeCard value="all" current={state.pagesMode} label="Extract all" />
            <ModeCard value="select" current={state.pagesMode} label="Select pages" />
          </RadioGroup>

          {state.pagesMode === "all" ? (
            <p className="text-sm text-muted-foreground">
              Every page becomes its own PDF
              {pageCount === null ? "" : `, so ${pageCount} of them`}.
            </p>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="split-pages" className="text-xs">
                Pages to extract
              </Label>
              <Input
                id="split-pages"
                placeholder="1,3-5"
                autoComplete="off"
                value={state.pages}
                onChange={(event) => set({ pages: event.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Single pages and ranges, separated by commas.
              </p>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <div className="flex items-start gap-2.5 border-t border-border pt-5">
        <Checkbox
          id="split-merge"
          checked={state.mergeOutput}
          onCheckedChange={(checked) => set({ mergeOutput: checked === true })}
        />
        <Label htmlFor="split-merge" className="text-sm leading-snug font-normal">
          Merge everything into one PDF
        </Label>
      </div>

      {issue ? (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {issue}
        </p>
      ) : (
        chunks && <Outcome chunks={chunks} />
      )}
    </div>
  );
}

function Outcome({ chunks }: { chunks: SplitChunk[] }) {
  if (chunks.length === 1) {
    return (
      <p className="text-sm text-muted-foreground">
        One PDF of{" "}
        <span className="font-medium text-foreground">
          {formatPageCount(chunks[0].pages.length)}
        </span>
        .
      </p>
    );
  }

  return (
    <p className="text-sm text-muted-foreground">
      <span className="font-medium text-foreground">{chunks.length} PDFs</span>, delivered as a
      ZIP.
    </p>
  );
}

/** A radio rendered as a pressable card, so the whole box is the hit target. */
function ModeCard({ value, current, label }: { value: string; current: string; label: string }) {
  const selected = value === current;

  return (
    <Label
      htmlFor={`split-mode-${value}`}
      data-selected={selected || undefined}
      className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-border p-3 text-sm font-normal transition-colors data-selected:border-brand data-selected:bg-brand/8"
    >
      <RadioGroupItem id={`split-mode-${value}`} value={value} />
      {label}
    </Label>
  );
}
