import { NextRequest, NextResponse } from "next/server";

import { checkRateLimit } from "@/lib/rate-limit";

type Fields = {
  name: string;
  email: string;
  message: string;
  /**
   * Honeypot. The name is deliberately non-semantic: calling it `company` or `phone` would
   * let browser and Google autofill populate it, flagging real people as bots.
   */
  hpField: string;
};

async function parseBody(req: NextRequest): Promise<Fields> {
  const contentType = req.headers.get("content-type") ?? "";

  if (
    contentType.includes("application/x-www-form-urlencoded") ||
    contentType.includes("multipart/form-data")
  ) {
    const fd = await req.formData();
    return {
      name: ((fd.get("name") as string | null) ?? "").trim(),
      email: ((fd.get("email") as string | null) ?? "").trim(),
      message: ((fd.get("message") as string | null) ?? "").trim(),
      hpField: ((fd.get("hp_field") as string | null) ?? "").trim(),
    };
  }

  const body = await req.json();
  return {
    name: String(body.name ?? "").trim(),
    email: String(body.email ?? "").trim(),
    message: String(body.message ?? "").trim(),
    hpField: String(body.hp_field ?? "").trim(),
  };
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const MAX_MESSAGE_LENGTH = 5000;

function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return req.headers.get("x-real-ip") ?? "anonymous";
}

export async function POST(req: NextRequest) {
  // The no-JS fallback posts url-encoded and expects a redirect; the hydrated fetch path
  // sends JSON and expects JSON back. Both are supported on purpose — see the contact form.
  const isFormPost = (req.headers.get("content-type") ?? "").includes("urlencoded");

  const ok = () =>
    isFormPost
      ? // 303, not 307: the browser must re-fetch the destination with GET rather than
        // replaying the POST.
        NextResponse.redirect(new URL("/contact?sent=1", req.url), 303)
      : NextResponse.json({ success: true });

  const fail = (error: string, status: number, message: string) =>
    isFormPost
      ? NextResponse.redirect(new URL(`/contact?error=${error}`, req.url), 303)
      : NextResponse.json({ success: false, message }, { status });

  let fields: Fields;
  try {
    fields = await parseBody(req);
  } catch {
    return fail("parse", 400, "Invalid submission. Please try again.");
  }

  const { name, email, message, hpField } = fields;

  // Honeypot tripped: report success so the bot gets no signal to adapt, and send nothing.
  if (hpField) return ok();

  if (!name || !email || !message) {
    return fail("fields", 400, "Please fill in all fields.");
  }
  if (!EMAIL_RE.test(email)) {
    return fail("email", 400, "Please enter a valid email address.");
  }
  if (message.length > MAX_MESSAGE_LENGTH) {
    return fail("length", 400, `Message must be ${MAX_MESSAGE_LENGTH} characters or fewer.`);
  }

  const { success: underLimit } = await checkRateLimit(clientIp(req));
  if (!underLimit) {
    return fail("rate", 429, "Too many messages from this address. Please try again later.");
  }

  const webhookUrl = process.env.N8N_CONTACT_WEBHOOK_URL;
  const apiKey = process.env.N8N_API_KEY;
  if (!webhookUrl || !apiKey) {
    console.error("[contact] Missing N8N_CONTACT_WEBHOOK_URL or N8N_API_KEY");
    return fail("server", 500, "The contact form is not configured. Please try again later.");
  }

  try {
    const res = await fetch(webhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
      },
      body: JSON.stringify({
        name,
        email,
        message,
        source: "PDFKit",
        submittedAt: new Date().toISOString(),
      }),
    });
    if (!res.ok) {
      console.error(`[contact] Webhook returned ${res.status}`);
      return fail("server", 502, "Could not send your message. Please try again later.");
    }
  } catch (err) {
    console.error("[contact] Webhook request failed:", err);
    return fail("server", 502, "Could not send your message. Please try again later.");
  }

  return ok();
}
