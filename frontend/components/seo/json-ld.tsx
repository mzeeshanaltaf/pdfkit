import { APP_DESCRIPTION, APP_NAME, SITE_URL } from "@/lib/constants";
import { TOOL_SEO } from "@/lib/seo/tool-content";
import { TOOLS, getTool, toolHref, type ToolId } from "@/lib/tools";

/**
 * Structured data, rendered on the server so it is in the HTML rather than injected after
 * hydration — a crawler that does not run our JS still sees it.
 *
 * Deliberately not emitting `HowTo`: Google retired those rich results in 2023, so the
 * markup would be weight with nothing behind it. The step list stays as plain semantic
 * HTML instead.
 */
function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      // The payload is our own module-level content, never user input.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

const abs = (path: string) => `${SITE_URL}${path}`;

/** The homepage, spelled the way its own `canonical` is: no trailing slash. */
const HOME = SITE_URL;

/** The app itself. Free, no sign-up, so `offers` is an explicit zero rather than absent. */
function webApplication(name: string, description: string, url: string) {
  return {
    "@type": "WebApplication",
    name,
    description,
    url,
    applicationCategory: "UtilitiesApplication",
    operatingSystem: "Any",
    browserRequirements: "Requires JavaScript",
    isAccessibleForFree: true,
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  };
}

/** Homepage graph: the site, plus the app, plus every tool as a linked entity. */
export function SiteJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@graph": [
          {
            "@type": "WebSite",
            "@id": abs("/#website"),
            name: APP_NAME,
            description: APP_DESCRIPTION,
            url: HOME,
            inLanguage: "en",
          },
          {
            ...webApplication(APP_NAME, APP_DESCRIPTION, HOME),
            "@id": abs("/#app"),
            featureList: TOOLS.map((tool) => tool.name),
          },
        ],
      }}
    />
  );
}

/**
 * Per-tool graph: breadcrumbs so the SERP shows a path rather than a bare URL, the tool as
 * its own WebApplication entity, and the FAQ block. FAQ rich results are now reserved for
 * authoritative sites, but the markup still tells search engines and LLMs what the page
 * answers, which is the part that matters here.
 */
export function ToolJsonLd({ toolId }: { toolId: ToolId }) {
  const tool = getTool(toolId);
  const seo = TOOL_SEO[toolId];
  const url = abs(toolHref(tool));

  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@graph": [
          {
            "@type": "BreadcrumbList",
            itemListElement: [
              { "@type": "ListItem", position: 1, name: APP_NAME, item: HOME },
              { "@type": "ListItem", position: 2, name: tool.name, item: url },
            ],
          },
          {
            ...webApplication(tool.name, tool.description, url),
            "@id": `${url}#app`,
            isPartOf: { "@id": abs("/#website") },
          },
          {
            "@type": "FAQPage",
            "@id": `${url}#faq`,
            mainEntity: seo.faqs.map(({ q, a }) => ({
              "@type": "Question",
              name: q,
              acceptedAnswer: { "@type": "Answer", text: a },
            })),
          },
        ],
      }}
    />
  );
}
