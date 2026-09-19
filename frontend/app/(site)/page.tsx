import { FolderX, Laptop, UserX } from "lucide-react";

import { ToolCard } from "@/components/landing/tool-card";
import { SiteJsonLd } from "@/components/seo/json-ld";
import { APP_DESCRIPTION, APP_TAGLINE } from "@/lib/constants";
import { TOOLS } from "@/lib/tools";

const PRINCIPLES = [
  {
    icon: Laptop,
    title: "Your machine does the work",
    body: "Merging, splitting, rotating, organising, numbering and page-to-image conversion all happen in the browser tab. Nothing is uploaded.",
  },
  {
    icon: FolderX,
    title: "The server keeps nothing",
    body: "Compression, OCR, passwords and image extraction need real tooling, so those files are sent, processed and deleted in the same request.",
  },
  {
    icon: UserX,
    title: "No account, no queue",
    body: "There is nothing to sign up for and no daily limit. Open a tool, drop a file, get the result.",
  },
];

export default function HomePage() {
  return (
    <>
      <section className="mx-auto w-full max-w-[1400px] px-4 pt-16 pb-10 sm:px-6 lg:pt-24">
        <div className="max-w-2xl">
          <h1 className="text-4xl font-semibold tracking-tighter text-balance md:text-5xl lg:text-6xl">
            {APP_TAGLINE}
          </h1>
          <p className="mt-5 max-w-[60ch] text-lg leading-relaxed text-muted-foreground">
            {APP_DESCRIPTION}
          </p>
        </div>
      </section>

      <section className="mx-auto w-full max-w-[1400px] px-4 pb-20 sm:px-6">
        <h2 className="sr-only">All tools</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {TOOLS.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
        </div>
      </section>

      <section className="border-t border-border bg-muted/40">
        <div className="mx-auto grid w-full max-w-[1400px] gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-16 lg:py-20">
          <h2 className="text-2xl font-semibold tracking-tight text-balance md:text-3xl">
            Built so your documents stay yours
          </h2>

          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-1 lg:gap-7">
            {PRINCIPLES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex gap-4">
                <Icon className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden />
                <div>
                  <h3 className="font-medium tracking-tight">{title}</h3>
                  <p className="mt-1.5 max-w-[58ch] text-sm leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <SiteJsonLd />
    </>
  );
}
