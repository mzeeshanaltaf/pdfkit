/**
 * The browser's half of the FastAPI service.
 *
 * Uploads go through `XMLHttpRequest` rather than `fetch`: fetch still cannot report
 * upload progress, and on a 40 MB scan the upload is most of the wait, so a real
 * percentage is the difference between "working" and "frozen".
 */

import { MAX_UPLOAD_BYTES, MAX_UPLOAD_LABEL } from "./constants";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

interface ApiErrorFlags {
  /**
   * The workspace is still intact and trying again — after a tweak, or just later — is a
   * sensible next step. ToolShell shows these as a toast and returns to the file list
   * instead of taking over the screen with a failure page.
   */
  recoverable?: boolean;
  /** The user caused this (cancelled a prompt, navigated away); say nothing at all. */
  silent?: boolean;
}

export class ApiError extends Error {
  /** HTTP status, or 0 when the request never got an answer. */
  readonly status: number;
  /** The backend's machine-readable `detail`, e.g. `password_required`. */
  readonly code: string;
  readonly recoverable: boolean;
  readonly silent: boolean;

  constructor(status: number, code: string, message: string, flags: ApiErrorFlags = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.recoverable = flags.recoverable ?? false;
    this.silent = flags.silent ?? false;
  }
}

/**
 * Backend `detail` codes that are identifiers rather than sentences. Anything not listed
 * is already a human sentence (`"sample.pdf is over the 50 MB limit."`) and is shown as-is.
 */
const MESSAGES: Record<string, string> = {
  password_required: "This PDF is password protected.",
  wrong_password: "That password did not open the file.",
  no_images_found: "There are no embedded images in this PDF to extract.",
  password_missing: "Enter a password first.",
  password_invalid: "A PDF password cannot contain a line break.",
  server_busy: "The server is busy with other documents. Try again in a moment.",
  processing_timed_out: "This file took too long to process, so it was stopped.",
  ocr_unavailable: "OCR is not available on this server right now.",
  needs_ocr:
    "This PDF is a scan, so there is no text to convert. Turn OCR on and try again.",
  document_unreadable: "This PDF could not be read well enough to convert.",
  document_too_complex: "This PDF is too large or complex to convert.",
  // The API is behind a short-lived token minted by this site. All four of these mean
  // "ask for a new one and go again", which `withFreshToken` does once on its own —
  // reaching a user means that retry failed too, which is a misconfiguration.
  auth_required: "This page needs a refresh before it can talk to the server.",
  auth_expired: "That took long enough for the session to lapse. Try again.",
  auth_invalid: "This page needs a refresh before it can talk to the server.",
  rate_limited: "Too many files in a short time. Wait a minute and try again.",
};

function cancelled(message: string): ApiError {
  return new ApiError(0, "cancelled", message, { recoverable: true, silent: true });
}

function networkError(): ApiError {
  return new ApiError(0, "network_error", "Could not reach the server. Check it is running and try again.", {
    recoverable: true,
  });
}

/**
 * Turns an error response body into an ApiError, whatever shape it came back in.
 *
 * Every one of them is recoverable, a 500 included: whatever broke, it broke over there,
 * and the file list in the browser is untouched. The next step is usually to retry, or to
 * change an option — a gentler compression level, a different OCR language — and go again.
 * Taking over the screen with a failure page would throw the workspace away to report
 * something it could have survived. The failure page is for errors raised on this side,
 * where the state really is in doubt.
 */
async function errorFromBody(status: number, body: Blob | null): Promise<ApiError> {
  let detail = "";
  try {
    const text = body ? await body.text() : "";
    const parsed: unknown = text ? JSON.parse(text) : null;
    const value = (parsed as { detail?: unknown } | null)?.detail;
    detail = typeof value === "string" ? value : "";
  } catch {
    // A non-JSON body (a proxy's HTML error page, say) tells us nothing useful.
  }

  const known = MESSAGES[detail];
  if (known) return new ApiError(status, detail, known, { recoverable: true });

  // A 5xx detail is a sanitised excerpt of tool output, and a proxy's error page has no
  // detail at all. Neither belongs in front of someone, so both get the same sentence and
  // the real thing stays on `code`.
  const message = status >= 500 || !detail ? "The server could not process this file." : detail;
  return new ApiError(status, detail || `http_${status}`, message, { recoverable: true });
}

function parseHeaders(raw: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of raw.trim().split(/[\r\n]+/)) {
    const separator = line.indexOf(":");
    if (separator === -1) continue;
    headers[line.slice(0, separator).trim().toLowerCase()] = line.slice(separator + 1).trim();
  }
  return headers;
}

const FILENAME_STAR = /filename\*=(?:utf-8|UTF-8)''([^;]+)/;
const FILENAME_QUOTED = /filename="([^"]*)"/;
const FILENAME_BARE = /filename=([^;]+)/;

/** Reads the download name the backend chose, so the UI never has to re-derive it. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;

  const encoded = FILENAME_STAR.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // A malformed percent-escape is not worth failing the whole download over.
    }
  }

  const quoted = FILENAME_QUOTED.exec(header) ?? FILENAME_BARE.exec(header);
  const name = quoted?.[1].trim();
  return name || fallback;
}

export interface ApiFileResponse {
  blob: Blob;
  /** From `Content-Disposition`, which the backend sets for every file response. */
  filename: string;
  /** Lower-cased response headers the CORS policy exposes, e.g. `x-original-size`. */
  headers: Record<string, string>;
}

export interface UploadOptions {
  /** 0-100 for the upload itself. The server's own work is reported over `/progress`. */
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
  /** Used only if the response somehow arrives without a Content-Disposition. */
  fallbackName?: string;
  /**
   * Extra request headers: the bearer token, and the `X-Job-Id` that ties this upload to
   * a progress stream. Sending either makes this a non-simple cross-origin request, so it
   * now costs one preflight — cached for the browser's default 600 s.
   */
  headers?: Record<string, string>;
}

/** The 50 MB cap, checked before a byte goes on the wire. Mirrors the server's own limit. */
export function assertUploadable(files: File[]): void {
  for (const file of files) {
    if (file.size > MAX_UPLOAD_BYTES) {
      throw new ApiError(0, "file_too_large", `${file.name} is over the ${MAX_UPLOAD_LABEL} limit.`, {
        recoverable: true,
      });
    }
  }
}

/**
 * Posts files plus form fields to the backend and returns the processed result.
 * One input comes back as a file, several come back as a zip — either way it is a blob
 * and a name here.
 */
export function uploadAndProcess(
  endpoint: string,
  files: File[],
  fields: Record<string, string> = {},
  { onProgress, signal, fallbackName = "download", headers = {} }: UploadOptions = {},
): Promise<ApiFileResponse> {
  assertUploadable(files);

  return new Promise<ApiFileResponse>((resolve, reject) => {
    if (signal?.aborted) {
      reject(cancelled("Cancelled."));
      return;
    }

    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    for (const [name, value] of Object.entries(fields)) form.append(name, value);

    const request = new XMLHttpRequest();
    request.open("POST", apiUrl(endpoint));
    request.responseType = "blob";
    for (const [name, value] of Object.entries(headers)) request.setRequestHeader(name, value);

    const abort = () => request.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const detach = () => signal?.removeEventListener("abort", abort);

    if (onProgress) {
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
      };
      // A small body can finish without ever firing a computable progress event.
      request.upload.onload = () => onProgress(100);
    }

    request.onload = () => {
      detach();
      const body = request.response as Blob | null;
      if (request.status >= 200 && request.status < 300 && body) {
        resolve({
          blob: body,
          filename: filenameFromDisposition(
            request.getResponseHeader("Content-Disposition"),
            fallbackName,
          ),
          headers: parseHeaders(request.getAllResponseHeaders()),
        });
        return;
      }
      void errorFromBody(request.status, body).then(reject, reject);
    };

    // Fires for a dropped connection, a refused one, and a CORS rejection alike — the
    // browser deliberately tells us no more than that.
    request.onerror = () => {
      detach();
      reject(networkError());
    };
    request.ontimeout = () => {
      detach();
      reject(networkError());
    };
    request.onabort = () => {
      detach();
      reject(cancelled("Cancelled."));
    };

    request.send(form);
  });
}

export interface PasswordRequest {
  filename: string;
  /** True when a password has already been tried on this file and rejected. */
  retry: boolean;
}

/** Asks the user for a password. Resolves to null if they give up. */
export type PasswordPrompt = (request: PasswordRequest) => Promise<string | null>;

/**
 * Upload one file, asking for a password whenever the backend says it needs one.
 *
 * The first attempt deliberately sends no password: a file locked with an owner password
 * only opens with the empty one, so a prompt there would be asking for something the user
 * does not have. `password_required` means the first attempt failed, `wrong_password`
 * means the one they typed did — the prompt is told which, so it can show an inline error
 * rather than a generic failure.
 */
export async function uploadWithPassword(
  endpoint: string,
  file: File,
  fields: Record<string, string>,
  options: UploadOptions & { requestPassword: PasswordPrompt },
): Promise<ApiFileResponse> {
  const { requestPassword, ...uploadOptions } = options;
  let password: string | null = null;

  for (;;) {
    try {
      const body = password === null ? fields : { ...fields, password };
      return await uploadAndProcess(endpoint, [file], body, uploadOptions);
    } catch (error) {
      const needsPassword =
        error instanceof ApiError &&
        (error.code === "password_required" || error.code === "wrong_password");
      if (!needsPassword) throw error;

      const supplied = await requestPassword({
        filename: file.name,
        retry: (error as ApiError).code === "wrong_password",
      });
      if (supplied === null) throw cancelled("Cancelled.");
      password = supplied;
    }
  }
}

export interface EventFrame {
  /** The SSE `event:` name — `hello`, `state` or `end`. */
  event: string;
  /** The `data:` line, still JSON text. */
  data: string;
}

/**
 * Reads a server-sent event stream with `fetch`, not `EventSource`.
 *
 * Three reasons, and the first is the one that decided it: `EventSource` cannot send an
 * `Authorization` header, so the progress route could not be authenticated at all. It also
 * shares the run's existing `AbortController`, and it has no automatic reconnection to
 * suppress — a progress stream that silently reopens after the job is gone is not a
 * feature.
 */
export async function* eventStream(
  path: string,
  { headers = {}, signal }: { headers?: Record<string, string>; signal?: AbortSignal } = {},
): AsyncGenerator<EventFrame> {
  const response = await fetch(apiUrl(path), { headers, signal, cache: "no-store" });
  if (!response.ok || !response.body) {
    throw await errorFromBody(response.status, response.body ? await response.blob() : null);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      // A frame is everything up to a blank line. Anything still in the buffer is a
      // partial frame and waits for the next chunk.
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = parseEventFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (frame) yield frame;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    // Tells the server we have gone, which is what lets it drop the stream slot.
    void reader.cancel().catch(() => {});
  }
}

function parseEventFrame(raw: string): EventFrame | null {
  let event = "message";
  const data: string[] = [];

  for (const line of raw.split("\n")) {
    // `: keep-alive` — a comment, and the thing holding the connection open through
    // Traefik. Not a frame, and no parser should treat it as one.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }

  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

/** Plain GET for the small JSON endpoints, e.g. the OCR language list. */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw cancelled("Cancelled.");
    throw networkError();
  }
  if (!response.ok) {
    throw await errorFromBody(response.status, await response.blob());
  }
  return (await response.json()) as T;
}
