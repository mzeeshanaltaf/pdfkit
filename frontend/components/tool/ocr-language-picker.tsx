"use client";

import { useId, useMemo, useState } from "react";
import { Languages, Search } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { OcrLanguage } from "./use-ocr-languages";

/** Mirrors the backend's MAX_OCR_LANGUAGES — each extra language costs a full pass. */
export const MAX_LANGUAGES = 3;

/**
 * Above this many installed models the flat list stops being scannable, so the search box
 * and the pinned-selection block switch on. Below it the panel stays exactly as it was —
 * a deployment that ships only English should not grow a filter for one row.
 */
const SEARCHABLE_FROM = 8;

interface OcrLanguagePickerProps {
  languages: OcrLanguage[];
  loading: boolean;
  selected: string[];
  onChange: (codes: string[]) => void;
  /** Heading above the list. */
  label?: string;
  /** Replaces the default note under the list. */
  hint?: string;
}

/**
 * The "which language is this document in" control, shared by OCR PDF, PDF to Word and
 * PDF to Markdown — all three send the same `languages` field to the same backend, and
 * three copies of this list would have drifted apart the first time the cap changed.
 */
export function OcrLanguagePicker({
  languages,
  loading,
  selected,
  onChange,
  label = "Document language",
  hint,
}: OcrLanguagePickerProps) {
  const [query, setQuery] = useState("");
  const searchId = useId();

  const full = selected.length >= MAX_LANGUAGES;
  const searchable = languages.length > SEARCHABLE_FROM;

  const toggle = (code: string) => {
    if (selected.includes(code)) {
      onChange(selected.filter((entry) => entry !== code));
      return;
    }
    if (full) return;
    // Order matters downstream: Tesseract weights the first language most heavily.
    onChange([...selected, code]);
  };

  // Picks are pinned above the list in the order they were made, so a filter can never
  // hide a checked language — otherwise typing "jap" would make an earlier Spanish pick
  // vanish and read as a deselection. It also puts the weighting order on screen, which
  // is what the hint below is talking about.
  const { pinned, rest } = useMemo(() => {
    const byCode = new Map(languages.map((language) => [language.code, language]));
    const needle = query.trim().toLowerCase();

    return {
      pinned: searchable
        ? selected.flatMap((code) => {
            const language = byCode.get(code);
            return language ? [language] : [];
          })
        : [],
      rest: languages.filter((language) => {
        if (searchable && selected.includes(language.code)) return false;
        if (!needle) return true;
        return (
          language.name.toLowerCase().includes(needle) ||
          language.code.toLowerCase().includes(needle)
        );
      }),
    };
  }, [languages, selected, query, searchable]);

  const row = (language: OcrLanguage) => {
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
          <span className="font-mono text-xs text-muted-foreground">{language.code}</span>
        </Label>
      </li>
    );
  };

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-medium">
          <Languages className="size-4 text-brand" aria-hidden />
          {label}
        </h2>
        <span className="text-xs text-muted-foreground">
          {selected.length} of {MAX_LANGUAGES}
        </span>
      </div>

      {loading ? (
        <div className="mt-3 space-y-2" aria-hidden>
          {[0, 1, 2].map((rowIndex) => (
            <div key={rowIndex} className="h-10 animate-pulse rounded-lg bg-muted" />
          ))}
          <span className="sr-only">Loading the available languages</span>
        </div>
      ) : (
        <>
          {searchable ? (
            <div className="relative mt-3">
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                id={searchId}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={`Search ${languages.length} languages`}
                aria-label="Search the available languages"
                className="pl-8"
              />
            </div>
          ) : null}

          {pinned.length > 0 ? (
            <>
              <ul className="mt-3 space-y-2">{pinned.map(row)}</ul>
              <p className="mt-2 text-xs text-muted-foreground">
                {pinned.length > 1
                  ? "Your picks, strongest first."
                  : "Your pick. Add up to two more."}
              </p>
            </>
          ) : null}

          {rest.length > 0 ? (
            <ul
              className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1"
              // The pinned block is static, so only this list needs to announce itself
              // when a filter narrows it.
              aria-live="polite"
            >
              {rest.map(row)}
            </ul>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
              {query.trim()
                ? `No language matches “${query.trim()}”.`
                : "Every installed language is already selected."}
            </p>
          )}
        </>
      )}

      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
        {selected.length === 0
          ? "Pick at least one language — OCR has to know what it is reading."
          : (hint ??
            `Pick up to ${MAX_LANGUAGES}. Choosing more languages than the document actually uses makes the result worse, not better — the first one you pick counts for most.`)}
      </p>
    </section>
  );
}
