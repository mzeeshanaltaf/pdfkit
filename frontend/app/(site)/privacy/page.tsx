import type { Metadata } from "next";
import Link from "next/link";

import { APP_NAME, MAX_UPLOAD_LABEL } from "@/lib/constants";
import { TOOLS, toolHref, type Tool } from "@/lib/tools";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: `How ${APP_NAME} handles your documents: no accounts, no stored files, and most tools never upload anything at all.`,
  alternates: { canonical: "/privacy" },
  openGraph: {
    title: `${APP_NAME} Privacy Policy`,
    description: `How ${APP_NAME} handles your documents: no accounts, no stored files, and most tools never upload anything at all.`,
    url: "/privacy",
  },
};

/** Read from the registry so the two lists below cannot drift from the real split. */
const BROWSER_TOOLS = TOOLS.filter((tool) => tool.runsIn === "browser");
const SERVER_TOOLS = TOOLS.filter((tool) => tool.runsIn !== "browser");

const LAST_UPDATED = "20 September 2026";

const LINK_CLASS =
  "rounded-sm text-foreground underline underline-offset-4 transition-colors hover:text-brand focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none";

/** Renders a set of tools as a linked prose list: "A, B and C". */
function ToolList({ tools }: { tools: Tool[] }) {
  return (
    <>
      {tools.map((tool, index) => (
        <span key={tool.id}>
          {index > 0 && (index === tools.length - 1 ? " and " : ", ")}
          <Link href={toolHref(tool)} className={LINK_CLASS}>
            {tool.name}
          </Link>
        </span>
      ))}
    </>
  );
}

const SUMMARY = [
  "Most tools never upload your file. The work happens inside your browser tab.",
  "The tools that do need a server delete the file as soon as the job finishes, in the same request.",
  "There are no accounts, no tracking cookies and no advertising or analytics profiles.",
  "The only thing we ever keep is what you voluntarily type into the contact form.",
];

export default function PrivacyPage() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 pt-16 pb-20 sm:px-6 lg:pt-24">
      <div className="max-w-2xl">
        <h1 className="text-4xl font-semibold tracking-tighter text-balance md:text-5xl">
          Privacy policy
        </h1>
        <p className="mt-5 max-w-[60ch] text-lg leading-relaxed text-muted-foreground">
          {APP_NAME} has no accounts, no database of documents and nothing to sign up for.
          This page explains exactly what that means for the files you open here.
        </p>
        <p className="mt-4 text-sm text-muted-foreground">Last updated: {LAST_UPDATED}</p>
      </div>

      <div className="mt-14 max-w-[70ch] space-y-12">
        <section>
          <h2 className="text-2xl font-semibold tracking-tight">The short version</h2>
          <ul className="mt-5 space-y-3 text-base leading-relaxed text-muted-foreground">
            {SUMMARY.map((point) => (
              <li key={point} className="flex gap-3">
                <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Tools that run in your browser</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            <ToolList tools={BROWSER_TOOLS} /> are implemented entirely in client-side
            JavaScript. When you drop a file into one of them, the file is read into your
            browser&apos;s memory, transformed there, and handed back to you as a download. It
            is never sent to us and it never crosses the network. You can confirm that in your
            browser&apos;s network inspector, or by disconnecting from the internet once the
            page has loaded — the tool still works.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Tools that use the server</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            <ToolList tools={SERVER_TOOLS} /> need document tooling that cannot run in a
            browser tab. For these the file is uploaded over HTTPS to our own server — not a
            third party — written to a temporary working directory, processed, returned to you
            and deleted before the request completes. Nothing is copied elsewhere, backed up
            or retained. Files are capped at {MAX_UPLOAD_LABEL} each.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            Passwords you enter for Protect PDF or Unlock PDF are used for that single
            operation only. They are never written to disk and never logged.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            PDF to JPG is the mixed case: rendering pages to images happens in your browser,
            while extracting the images already embedded in a PDF uses the server, on the same
            terms as the tools above.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">The contact form</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            If you write to us through the{" "}
            <Link href="/contact" className={LINK_CLASS}>
              contact page
            </Link>
            , the name, email address and message you type are forwarded to our own automation
            service and delivered to us as an email, so that we can read the message and
            reply. That information is used for nothing else, and you are not added to any
            mailing list.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            To stop the form being used for spam, submissions are rate limited per IP address.
            That check keeps a short-lived counter keyed to your IP in a hosted Redis
            instance; the counter expires on its own and is not tied to anything else about
            you. The form also carries a hidden field that only automated scripts fill in.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Anonymous usage counters</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            Each time a tool finishes, is cancelled, or fails, we record a single anonymous
            counter row: which tool, how many files and pages, how large they were, how long
            it took, and whether it succeeded. This is what tells us which tools are actually
            used, not a record of what any one person did.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            No IP address is ever stored. Instead, each row carries a one-way hash of your IP
            address combined with a secret that rotates every day, so the same visitor hashes
            the same way only within a single day and cannot be linked across days or back to
            an IP address. The contents of your file are never part of this: only counts and
            sizes are recorded, never the document itself.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Cookies and analytics</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            {APP_NAME} sets no tracking cookies and loads no analytics or advertising scripts.
            Your light or dark theme preference is kept in your browser&apos;s own local
            storage so the site does not flash the wrong theme on your next visit; that value
            stays on your device and is never sent to us.
          </p>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            Like any web server, ours writes ordinary request logs — timestamp, IP address,
            requested path, response status — which exist to diagnose faults and are rotated
            out in the normal course of operation. They contain no document contents.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Your rights</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            Because there are no accounts and no stored documents, there is generally no
            personal data of yours for us to show you, correct or erase. The exception is a
            message you have sent through the contact form — ask us and we will delete it.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold tracking-tight">Changes to this policy</h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            If how {APP_NAME} handles files ever changes, this page changes with it and the
            date above is updated. Questions about any of it are a perfectly good reason to
            use the{" "}
            <Link href="/contact" className={LINK_CLASS}>
              contact form
            </Link>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
