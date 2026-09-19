import type { Metadata } from "next";
import { Lock, MessageSquare, Server } from "lucide-react";

import { ContactForm } from "@/components/contact/contact-form";
import { APP_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Contact Us",
  description: `Report a bug, request a tool, or ask how ${APP_NAME} handles your files. Messages go straight to a person — no account needed.`,
  alternates: { canonical: "/contact" },
  openGraph: {
    title: `Contact ${APP_NAME}`,
    description: `Report a bug, request a tool, or ask how ${APP_NAME} handles your files.`,
    url: "/contact",
  },
};

/**
 * Short codes the API route sets on the no-JS redirect (`?error=…`), mapped to copy.
 * Keep these keys in step with the `fail()` calls in `app/api/contact/route.ts`.
 */
const ERROR_MESSAGES: Record<string, string> = {
  fields: "Please fill in all fields.",
  email: "Please enter a valid email address.",
  length: "Message must be 5000 characters or fewer.",
  rate: "Too many messages from this address. Please try again later.",
  server: "The contact form is unavailable right now. Please try again later.",
  parse: "Invalid submission. Please try again.",
};

const REASONS = [
  {
    icon: MessageSquare,
    title: "Something broke",
    body: "A file that would not process, a result that came back wrong, a page that misbehaved. Tell us which tool and what you fed it.",
  },
  {
    icon: Server,
    title: "A tool you want",
    body: "If the tool you reach for is missing, say so — that is how the list grows.",
  },
  {
    icon: Lock,
    title: "How your files are handled",
    body: "Questions about what runs in your browser, what reaches the server, and what is kept. Short answer: nothing is kept.",
  },
];

type Props = {
  searchParams: Promise<{ sent?: string; error?: string }>;
};

export default async function ContactPage({ searchParams }: Props) {
  const { sent, error } = await searchParams;
  const initialError = error
    ? (ERROR_MESSAGES[error] ?? "Something went wrong. Please try again.")
    : undefined;

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 pt-16 pb-20 sm:px-6 lg:pt-24">
      <div className="max-w-2xl">
        <h1 className="text-4xl font-semibold tracking-tighter text-balance md:text-5xl">
          Contact us
        </h1>
        <p className="mt-5 max-w-[60ch] text-lg leading-relaxed text-muted-foreground">
          There is no support queue and no ticket number — the form below reaches a person.
          Bug reports, tool requests and questions are all welcome.
        </p>
      </div>

      <div className="mt-12 grid gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,4fr)] lg:gap-16">
        <div className="rounded-2xl border border-border bg-card p-6 sm:p-8">
          <ContactForm initialSuccess={!!sent} initialError={initialError} />
        </div>

        <div>
          <h2 className="text-xl font-semibold tracking-tight">What to write about</h2>
          <div className="mt-6 grid gap-7 sm:grid-cols-2 lg:grid-cols-1">
            {REASONS.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex gap-4">
                <Icon className="mt-0.5 size-5 shrink-0 text-brand" aria-hidden />
                <div>
                  <h3 className="font-medium tracking-tight">{title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
