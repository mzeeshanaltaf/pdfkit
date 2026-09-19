import { APP_DESCRIPTION, APP_NAME, MAX_UPLOAD_LABEL, SITE_URL } from "@/lib/constants";
import { TOOL_SEO } from "@/lib/seo/tool-content";
import { TOOLS, toolHref } from "@/lib/tools";

/**
 * `/llms.txt` — the llmstxt.org convention: one markdown file describing the site for an
 * LLM that lands here without crawling it, so the tool list and the privacy model do not
 * have to be inferred from JavaScript-rendered pages.
 *
 * Generated from the registry rather than committed to `public/`, so it cannot drift out of
 * step with the tools that actually exist. It is a Route Handler, but a fully static one:
 * it reads no request, so `force-static` lets it prerender at build time like every other
 * route in this app.
 */
export const dynamic = "force-static";

function body(): string {
  const runsIn = {
    browser: "runs entirely in the browser, file never uploaded",
    backend: `runs on the server, file processed and deleted in the same request, ${MAX_UPLOAD_LABEL} limit`,
    hybrid: `page rendering runs in the browser; image extraction runs on the server, ${MAX_UPLOAD_LABEL} limit`,
  } as const;

  const lines: string[] = [
    `# ${APP_NAME}`,
    "",
    `> ${APP_DESCRIPTION}`,
    "",
    `${APP_NAME} is a self-hosted PDF toolkit with ten tools. There are no user accounts, no`,
    "sign-up and no stored files. Six of the ten tools do their work inside the browser tab with",
    "pdf-lib and pdf.js, so those documents never leave the visitor's computer. The remaining",
    "tools need native binaries (Ghostscript, qpdf, Tesseract) and therefore upload the file,",
    "process it, and delete it within the same HTTP request. Nothing is retained either way.",
    "",
    "## Tools",
    "",
  ];

  for (const tool of TOOLS) {
    lines.push(
      `- [${tool.name}](${SITE_URL}${toolHref(tool)}): ${tool.description} (${runsIn[tool.runsIn]})`,
    );
  }

  lines.push("", "## Common questions", "");

  for (const tool of TOOLS) {
    const seo = TOOL_SEO[tool.id];
    lines.push(`### ${tool.name}`, "");
    for (const { q, a } of seo.faqs) {
      lines.push(`- **${q}** ${a}`);
    }
    lines.push("");
  }

  lines.push(
    "## Notes",
    "",
    `- Pricing: free. ${APP_NAME} is self-hosted and has no paid tier, quota or daily limit.`,
    "- Accounts: none. There is nothing to sign up for and no session to keep.",
    "- Retention: zero. Browser-side tools upload nothing; server-side tools delete the file",
    "  as the request ends.",
    `- Upload cap: ${MAX_UPLOAD_LABEL} per file, and only for the tools that use the server.`,
    "- OCR languages: English is installed. The live list is served from `GET /ocr/languages`.",
    "",
  );

  return lines.join("\n");
}

export function GET(): Response {
  return new Response(body(), {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=0, must-revalidate",
    },
  });
}
