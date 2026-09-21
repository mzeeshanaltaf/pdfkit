"use client";

import { eventStream, uploadAndProcess, type ApiFileResponse } from "@/lib/api";
import { withFreshToken } from "@/lib/token";

import type { ToolPlacement, ToolRunContext } from "./types";

interface BackendRunOptions {
  /** Stage text for the part of the job that happens on the server. */
  workingStage: string;
  /** Download name to fall back on if the response carries no Content-Disposition. */
  fallbackName: string;
}

/** One `state` frame from `/progress`, as the backend publishes it. */
interface ProgressState {
  phase: "queued" | "running";
  file: { index: number; total: number; name: string };
  step: string;
  percent: number | null;
  placement: ToolPlacement;
}

/** Reads `X-Processed-On`, or undefined if it is missing or not one of the two values. */
function placementFromHeader(headers: Record<string, string>): ToolPlacement | undefined {
  const value = headers["x-processed-on"];
  return value === "server" || value === "sandbox" ? value : undefined;
}

/**
 * If the server has said nothing this long after the upload landed, fall back to the
 * indeterminate bar. Two seconds is comfortably longer than the round trip and short
 * enough that a blocked `/progress` route is not a visible stall.
 */
const FALLBACK_AFTER_MS = 2000;

const QUEUED_STAGE = "Waiting for a free slot — the server is busy";

/**
 * Live progress for a batched backend tool, over the SSE channel at `/progress/{job}`.
 *
 * **The bridge never rejects.** The run's promise is the upload alone, and every failure
 * here — a blocked route, a 429 on the stream, a malformed frame — leaves the tool working
 * exactly as it did before any of this existed: a real upload percentage, then an
 * indeterminate bar. Progress is not allowed to be the thing that breaks a conversion.
 *
 * **Two phases, never blended.** The upload owns the bar from 0 to 100, because that
 * percentage is real and the server cannot begin until the last byte lands. At 100 it
 * hands over to the server's own numbers and never hands back.
 */
function createProgressBridge(
  { setProgress, setStage, setDetail, setPlacement, signal }: ToolRunContext,
  { workingStage }: BackendRunOptions,
) {
  // 32 hex characters, which is the shape the backend's route accepts.
  const jobId = crypto.randomUUID().replace(/-/g, "");

  const controller = new AbortController();
  signal.addEventListener("abort", () => controller.abort(), { once: true });

  let uploading = true;
  let latest: ProgressState | null = null;
  let fallback: ReturnType<typeof setTimeout> | null = null;

  const render = (state: ProgressState) => {
    setProgress(state.percent);
    setStage(state.phase === "queued" ? QUEUED_STAGE : state.step || workingStage);
    setDetail(
      state.file.total > 1
        ? `File ${state.file.index} of ${state.file.total} — ${state.file.name}`
        : state.file.name || null,
    );
    // The live signal: arrives with the first frame, and corrects itself the moment a
    // fallback happens mid-batch. The response header below is what has the final say.
    setPlacement(state.placement);
  };

  const stopFallback = () => {
    if (fallback !== null) clearTimeout(fallback);
    fallback = null;
  };

  return {
    jobId,

    /**
     * Start listening. Deliberately not awaited, and it cannot throw at the caller.
     *
     * Called once per upload attempt, so it also resets the phase: a 401 retry starts a
     * second upload from zero, and the bar has to go back to following it.
     */
    listen(token: string) {
      uploading = true;
      latest = null;
      stopFallback();

      void (async () => {
        try {
          for await (const frame of eventStream(`/progress/${jobId}`, {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          })) {
            if (frame.event === "end") return;
            if (frame.event !== "state") continue;

            latest = JSON.parse(frame.data) as ProgressState;
            // Frames that arrive mid-upload are kept, not shown: the upload still
            // owns the bar, and the handover applies whatever the newest one is.
            if (uploading) continue;
            stopFallback();
            render(latest);
          }
        } catch {
          // The bar degrades to indeterminate on its own. Nothing to report: the
          // conversion itself is unaffected, and a toast about a progress stream
          // would be noise about something the user did not ask for.
        }
      })();
    },

    onUploadProgress(percent: number) {
      if (percent < 100) {
        setProgress(percent);
        return;
      }
      if (!uploading) return;
      uploading = false;

      if (latest) {
        render(latest);
        return;
      }
      // Give the server a moment to say something before giving up on it.
      fallback = setTimeout(() => {
        setProgress(null);
        setStage(workingStage);
      }, FALLBACK_AFTER_MS);
    },

    close() {
      stopFallback();
      controller.abort();
    },
  };
}

/**
 * The shared shape of a backend tool's run: token, job id, live upload percentage, then
 * the server's own progress until the file comes back.
 */
export async function runBackendTool(
  context: ToolRunContext,
  endpoint: string,
  fields: Record<string, string>,
  options: BackendRunOptions,
): Promise<ApiFileResponse> {
  const { files, setProgress, setStage, setPlacement } = context;
  const bridge = createProgressBridge(context, options);

  setStage(files.length === 1 ? "Uploading your file" : `Uploading ${files.length} files`);
  setProgress(0);

  try {
    const response = await withFreshToken((token) => {
      // Opened before the POST so a job that finishes in milliseconds cannot slip by
      // unseen; the backend keeps a finished job's channel around briefly for the
      // opposite case, where the stream is the one that arrives late.
      bridge.listen(token);
      return uploadAndProcess(
        endpoint,
        files.map((file) => file.file),
        fields,
        {
          signal: context.signal,
          fallbackName: options.fallbackName,
          headers: { Authorization: `Bearer ${token}`, "X-Job-Id": bridge.jobId },
          onProgress: (percent) => bridge.onUploadProgress(percent),
        },
      );
    });
    // Authoritative: progress is best-effort and may never connect, but a response
    // that arrived definitely carries this header — set for every backend response.
    const processedOn = placementFromHeader(response.headers);
    if (processedOn) setPlacement(processedOn);
    return response;
  } finally {
    bridge.close();
  }
}

/** Reads a numeric response header, or undefined when it is missing or not a number. */
export function numericHeader(
  headers: Record<string, string>,
  name: string,
): number | undefined {
  const value = Number(headers[name]);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}
