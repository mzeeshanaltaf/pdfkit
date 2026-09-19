"use client";

import { CheckCircle2, Loader2, Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Status = "idle" | "loading" | "success" | "error";

type Props = {
  /** Set when the no-JS fallback redirected back with `?sent=1`. */
  initialSuccess?: boolean;
  /** Resolved copy for a `?error=` code from the same fallback. */
  initialError?: string;
};

const MAX_MESSAGE_LENGTH = 5000;

/**
 * Progressive enhancement, deliberately.
 *
 * A `"use client"` form inside a server component can render correct HTML and still fail
 * to hydrate silently — `onSubmit` never fires and the UI looks alive but is dead. So the
 * form keeps a real `action`/`method` that posts to the same route, and `onSubmit` only
 * upgrades that path when React is actually running. Removing either half reintroduces
 * the failure mode.
 */
export function ContactForm({ initialSuccess = false, initialError }: Props) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  // Honeypot, mirrored into state so the hydrated submit forwards it too.
  const [hpField, setHpField] = useState("");

  const [status, setStatus] = useState<Status>(
    initialSuccess ? "success" : initialError ? "error" : "idle",
  );
  const [errorMsg, setErrorMsg] = useState(initialError ?? "");

  const handleSubmit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!name.trim() || !email.trim() || !message.trim()) {
      setStatus("error");
      setErrorMsg("Please fill in all fields.");
      return;
    }

    setStatus("loading");
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, message, hp_field: hpField }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setStatus("success");
      } else {
        setStatus("error");
        setErrorMsg(data.message ?? "Something went wrong. Please try again.");
      }
    } catch {
      setStatus("error");
      setErrorMsg("Failed to send. Check your connection and try again.");
    }
  };

  if (status === "success") {
    return (
      <div
        role="status"
        className="flex flex-col items-center gap-4 rounded-2xl border border-brand/25 bg-brand/5 px-6 py-12 text-center"
      >
        <span className="flex size-12 items-center justify-center rounded-full bg-brand/10">
          <CheckCircle2 className="size-6 text-brand" aria-hidden />
        </span>
        <h2 className="text-xl font-semibold tracking-tight">Message sent</h2>
        <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
          Thanks — we read every message, and will reply if one is needed.
        </p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-1"
          onClick={() => {
            setName("");
            setEmail("");
            setMessage("");
            setErrorMsg("");
            setStatus("idle");
          }}
        >
          Send another
        </Button>
      </div>
    );
  }

  return (
    <form
      action="/api/contact"
      method="post"
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-5"
    >
      {/* Honeypot: off-screen, out of the a11y tree, out of the tab order and out of
          autofill's reach. Real people never see it; bots that fill every input do. */}
      <div
        aria-hidden="true"
        className="absolute top-[-9999px] left-[-9999px] size-0 overflow-hidden"
      >
        <label htmlFor="hp_field">Leave this field empty</label>
        <input
          id="hp_field"
          name="hp_field"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={hpField}
          onChange={(event) => setHpField(event.target.value)}
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            name="name"
            type="text"
            required
            autoComplete="name"
            placeholder="Your name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="message">Message</Label>
        <Textarea
          id="message"
          name="message"
          required
          rows={7}
          maxLength={MAX_MESSAGE_LENGTH}
          placeholder="A bug report, a feature idea, or a question about how a tool works…"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          className="resize-y"
        />
        <p className="text-xs text-muted-foreground">
          Please don&apos;t paste sensitive document contents — this message is delivered by email.
        </p>
      </div>

      {status === "error" && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
        >
          {errorMsg}
        </p>
      )}

      <Button type="submit" size="lg" disabled={status === "loading"} className="self-start">
        {status === "loading" ? (
          <Loader2 data-icon="inline-start" className="animate-spin" aria-hidden />
        ) : (
          <Send data-icon="inline-start" aria-hidden />
        )}
        {status === "loading" ? "Sending…" : "Send message"}
      </Button>
    </form>
  );
}
