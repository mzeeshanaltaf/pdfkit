import type { LucideIcon } from "lucide-react";
import {
  FileArchive,
  FileImage,
  FileSearch,
  Hash,
  LayoutGrid,
  Lock,
  Merge,
  RotateCw,
  Scissors,
  Unlock,
} from "lucide-react";
import type { Metadata } from "next";

import { APP_NAME } from "./constants";
import { TOOL_SEO } from "./seo/tool-content";

/** The route `app/opengraph-image.tsx` is served from. Resolved against `metadataBase`. */
const OG_IMAGE = {
  url: "/opengraph-image",
  width: 1200,
  height: 630,
  alt: `${APP_NAME} — every PDF tool on one page`,
};

export type ToolId =
  | "merge"
  | "split"
  | "compress"
  | "pdf-to-jpg"
  | "organize"
  | "rotate"
  | "page-numbers"
  | "protect"
  | "unlock"
  | "ocr";

/**
 * Where the work happens. `browser` tools never upload; `backend` tools post the file to
 * the FastAPI service; `hybrid` tools pick per option (PDF to JPG: pages vs embedded images).
 * Anything that can reach the backend is subject to the upload cap.
 */
export type ToolRuntime = "browser" | "backend" | "hybrid";

/** Colour family for the tool's icon tile. Grouped by what the tool does, not per tool. */
export type ToolAccent = "teal" | "indigo" | "amber" | "rose";

export interface Tool {
  id: ToolId;
  slug: string;
  name: string;
  /** One line for the landing card. */
  tagline: string;
  /** Longer sentence for page metadata and the tool sidebar. */
  description: string;
  icon: LucideIcon;
  accent: ToolAccent;
  /** Whether the tool accepts more than one file. */
  multiple: boolean;
  ctaLabel: string;
  runsIn: ToolRuntime;
}

export const TOOLS: Tool[] = [
  {
    id: "merge",
    slug: "merge-pdf",
    name: "Merge PDF",
    tagline: "Combine files in the order you choose.",
    description:
      "Combine several PDFs into a single document, dragging the files into the order you want.",
    icon: Merge,
    accent: "teal",
    multiple: true,
    ctaLabel: "Merge PDF",
    runsIn: "browser",
  },
  {
    id: "split",
    slug: "split-pdf",
    name: "Split PDF",
    tagline: "Cut one file into ranges or single pages.",
    description:
      "Split a PDF into page ranges or pull out individual pages, as one file or a zip.",
    icon: Scissors,
    accent: "teal",
    multiple: false,
    ctaLabel: "Split PDF",
    runsIn: "browser",
  },
  {
    id: "organize",
    slug: "organize-pdf",
    name: "Organize PDF",
    tagline: "Reorder, rotate and delete pages.",
    description:
      "Rearrange pages across one or more PDFs, rotate or delete any of them, then build a new document.",
    icon: LayoutGrid,
    accent: "teal",
    multiple: true,
    ctaLabel: "Organize PDF",
    runsIn: "browser",
  },
  {
    id: "rotate",
    slug: "rotate-pdf",
    name: "Rotate PDF",
    tagline: "Turn pages the right way up.",
    description: "Rotate every page of a PDF, or each file on its own, and save the result.",
    icon: RotateCw,
    accent: "teal",
    multiple: true,
    ctaLabel: "Rotate PDF",
    runsIn: "browser",
  },
  {
    id: "page-numbers",
    slug: "add-page-numbers",
    name: "Page numbers",
    tagline: "Stamp numbers exactly where you want them.",
    description:
      "Add page numbers to a PDF, choosing position, margin, starting number, font and format.",
    icon: Hash,
    accent: "teal",
    multiple: true,
    ctaLabel: "Add page numbers",
    runsIn: "browser",
  },
  {
    id: "compress",
    slug: "compress-pdf",
    name: "Compress PDF",
    tagline: "Shrink the file, keep it readable.",
    description:
      "Reduce PDF file size with three levels of compression, and see how much each file saved.",
    icon: FileArchive,
    accent: "indigo",
    multiple: true,
    ctaLabel: "Compress PDF",
    runsIn: "backend",
  },
  {
    id: "pdf-to-jpg",
    slug: "pdf-to-jpg",
    name: "PDF to JPG",
    tagline: "Render pages, or pull out embedded images.",
    description:
      "Turn every page into a JPG, or extract the images already embedded in the document.",
    icon: FileImage,
    accent: "amber",
    multiple: true,
    ctaLabel: "Convert to JPG",
    runsIn: "hybrid",
  },
  {
    id: "ocr",
    slug: "ocr-pdf",
    name: "OCR PDF",
    tagline: "Make a scan searchable.",
    description:
      "Run optical character recognition over a scanned PDF so the text can be searched and selected.",
    icon: FileSearch,
    accent: "amber",
    multiple: true,
    ctaLabel: "Apply OCR",
    runsIn: "backend",
  },
  {
    id: "protect",
    slug: "protect-pdf",
    name: "Protect PDF",
    tagline: "Lock a document with a password.",
    description:
      "Encrypt a PDF with a password so it cannot be opened by anyone who does not have it.",
    icon: Lock,
    accent: "rose",
    multiple: true,
    ctaLabel: "Protect PDF",
    runsIn: "backend",
  },
  {
    id: "unlock",
    slug: "unlock-pdf",
    name: "Unlock PDF",
    tagline: "Remove a password you already know.",
    description:
      "Strip the password from a PDF you have the right to open, so it opens without a prompt.",
    icon: Unlock,
    accent: "rose",
    multiple: true,
    ctaLabel: "Unlock PDF",
    runsIn: "backend",
  },
];

const TOOLS_BY_ID = new Map(TOOLS.map((tool) => [tool.id, tool]));
const TOOLS_BY_SLUG = new Map(TOOLS.map((tool) => [tool.slug, tool]));

export function getTool(id: ToolId): Tool {
  const tool = TOOLS_BY_ID.get(id);
  if (!tool) throw new Error(`Unknown tool id: ${id}`);
  return tool;
}

export function getToolBySlug(slug: string): Tool | undefined {
  return TOOLS_BY_SLUG.get(slug);
}

export function toolHref(tool: Tool): string {
  return `/${tool.slug}`;
}

/** The "continue to another tool" suggestions on the result screen. */
export function relatedTools(id: ToolId, limit = 3): Tool[] {
  const current = getTool(id);
  const sameAccent = TOOLS.filter((tool) => tool.id !== id && tool.accent === current.accent);
  const rest = TOOLS.filter((tool) => tool.id !== id && tool.accent !== current.accent);
  return [...sameAccent, ...rest].slice(0, limit);
}

/**
 * Per-page metadata, so no tool route hardcodes its own title.
 *
 * The share image has to be named here. Next merges `app/opengraph-image.tsx` into a
 * route's metadata only while that route leaves `openGraph` alone — setting any of it, as
 * every tool does for its own title, drops the inherited image with it.
 */
export function toolMetadata(id: ToolId): Metadata {
  const tool = getTool(id);
  const href = toolHref(tool);
  // The root layout's title template supplies the "| PDFKit" suffix for the tab, but a
  // share card has no template behind it, so the OG title carries the product name itself.
  const shareTitle = `${tool.name} | ${APP_NAME}`;

  return {
    // The search-facing title, which is longer and more explicit than the UI label: a tab
    // reading "Merge PDF" wastes most of the ~60 characters a SERP will show.
    title: TOOL_SEO[id].title,
    description: tool.description,
    alternates: { canonical: href },
    openGraph: {
      type: "website",
      siteName: APP_NAME,
      title: shareTitle,
      description: tool.description,
      url: href,
      locale: "en_US",
      images: [OG_IMAGE],
    },
    twitter: {
      card: "summary_large_image",
      title: shareTitle,
      description: tool.description,
      images: [OG_IMAGE],
    },
  };
}

/** Tailwind classes per accent, written out in full so the compiler can see them. */
export const ACCENT_TILE_CLASS: Record<ToolAccent, string> = {
  teal: "bg-teal-500/12 text-teal-700 dark:bg-teal-400/15 dark:text-teal-300",
  indigo: "bg-indigo-500/12 text-indigo-700 dark:bg-indigo-400/15 dark:text-indigo-300",
  amber: "bg-amber-500/15 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300",
  rose: "bg-rose-500/12 text-rose-700 dark:bg-rose-400/15 dark:text-rose-300",
};
