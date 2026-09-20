# Phase 8 — Live progress for backend jobs + API protection

## Goal
Honest live progress ("File 2 of 5 — report.pdf", 41%, page 12 of 29) for every backend
tool, a working Cancel button, and an API that is a cost gate rather than an open service.

## Prerequisites
Phase 7 complete — PDFKit deployed and live on Coolify.

## Context

Two production problems, both in the backend path.

**1. The progress bar goes blind the moment the upload finishes.** `runBackendTool`
(`frontend/components/tool/backend-run.ts`) shows a real byte-accurate percentage while the
upload is in flight, then calls `setProgress(null)` and hands over to an indeterminate
pulsing bar with one static line of stage text — for the entire server-side job. Worse,
every backend tool posts **all files in one request**, so there is no notion of "file 2 of
5" anywhere in the system. A five-file OCR batch can sit on that pulsing bar for minutes
with nothing changing, which reads as frozen. The one exception is Unlock, which already
loops per file and is the shape everything else should have.

**2. `api.pdfkit.zeeshanai.cloud` is completely open.** No auth, no rate limiting, no
per-IP anything — `main.py` has CORS and nothing else. CORS stops browsers from other
origins; it stops `curl` not at all. Anyone can POST 50 MB PDFs and occupy both
`MAX_CONCURRENT_JOBS` slots with 600-second OCR runs indefinitely, using the VPS as a free
PDF service.

## Decisions taken before the detail

**Keep the single batched POST; do not split into one request per file.** Splitting would
give file-level progress for free, but it would break the batched anydoc call that
PDF→Markdown depends on ("one interpreter start, not fifty"), lose server-side zipping and
Compress's `X-Original-Size`/`X-Result-Size` aggregation, and multiply the request count.
Since we are building the progress channel anyway for intra-file percentages, file-level
events come off the same registry at near-zero extra cost.

**Cancel gets cooperative server-side teardown.** The known wart of a batched POST is that
aborting the XHR does not stop the server. Fix it cheaply: the per-file service loops check
`await request.is_disconnected()` between files and bail. Upload bodies are fully streamed
to disk before processing starts, so `is_disconnected` is reliable here. Granularity is one
file, which is the right granularity.

**Use `fetch` + `ReadableStream` for SSE, not `EventSource`.** Same wire protocol, but it
can send an `Authorization` header (which solves authenticating the progress stream
outright), it shares the existing `AbortController`, and it has no auto-reconnect to
suppress.

**Auth is a cost gate, not a security boundary.** A short-TTL token minted by the Next
server stops scripted third-party use of the API. It does not stop someone copying a token
out of devtools — nothing short of accounts would, and this app deliberately has none. That
sentence goes in the module docstring so nobody later mistakes it for authentication.

### Three assumptions that turned out wrong — the design accounts for these

| Assumed | Actual |
|---|---|
| Dropping OCRmyPDF's `--quiet` yields per-page stderr | **No.** `ocrmypdf/__main__.py` disables the progress bar whenever stderr is not a TTY, which under `PIPE` is always. Must use the documented `--plugin` + `get_progressbar_class` hook, and **keep** `--quiet`. |
| A custom header needs a CORS change | Already covered — `main.py` passes `allow_headers=["*"]`, and Starlette echoes requested headers. But the upload POST stops being a CORS-simple request, so it gains a preflight (cached 600 s). |
| Per-IP limits will see the real client IP | **No.** `backend/Dockerfile` runs uvicorn with no `--forwarded-allow-ips`; the default is `127.0.0.1`, Traefik connects from a `172.x` bridge address and is therefore untrusted, so `request.client.host` is *Traefik* for everybody. Must be fixed **before** limits are enabled or the whole site shares one bucket. |

---

## Part A — Live progress

### A1. Streaming subprocess runner — `backend/app/services/runner.py`

The enabler. `_spawn` currently does `await asyncio.wait_for(process.communicate(), ...)`,
which buffers until exit. Replace with a chunked reader that **drains both pipes
concurrently** and splits lines as they arrive, preserving exactly today's semantics: same
`ToolResult` (full stdout/stderr strings), one timeout over the whole run, `process.kill()`
+ `await process.wait()` + `HTTPException(504, "processing_timed_out")`.

- `run()` gains `on_line: Callable[[str, str], None] | None = None` and forwards it. Only 4
  call sites pass it.
- **Both pipes must be drained in one `asyncio.gather`.** Reading one at a time is the
  classic deadlock — a chatty child fills the 64 KiB buffer on the other stream and blocks
  until the op timeout. This is precisely what `communicate()` was protecting against.
- **Do not use `StreamReader.readline()`** — it raises on a line past its 64 KiB limit. Use
  chunked `read(64KiB)` plus a manual split on CR/LF/CRLF (splitting on a bare carriage
  return matters: a tool emitting carriage-return progress would otherwise buffer forever).
- Cap captured output at 1 MiB per stream and the pending-line buffer at 64 KiB. This is a
  behaviour change only in the pathological case (today it is unbounded); note it in the
  docstring.
- Use `async with asyncio.timeout(timeout):` over both the gather and `process.wait()`,
  then cancel-and-suppress the pumps explicitly before killing.

**Ship this alone and verify the full suite stays green before anything else.** It is the
riskiest edit in the plan and the only one that can break every tool at once.

### A2. Progress registry — new `backend/app/services/progress.py`

**Latest-value snapshot + `asyncio.Event`, not a Queue.** Progress is state, not a log. A
queue either back-pressures the producer (a subprocess line pump must never block) or needs
drop logic; overwrite-and-`set()` coalesces for free, is O(1) per job, and losing
intermediate frames is exactly right for a bar. Publishing is synchronous and non-blocking,
so it is safe to call from a line-pump callback.

```python
@dataclass(slots=True)
class Snapshot:
    phase: str            # "queued" | "running"
    file_index: int; file_total: int; file_name: str
    step: str; percent: float | None; terminal: bool
```

- `Registry` is a `dict[str, Channel]` capped at `MAX_TRACKED_JOBS` (256), swept for expiry
  on every touch. At the cap it **refuses** to create and the POST proceeds with a
  `NullPublisher` — progress must never be able to fail a request.
- A channel created by a subscriber before the producer registers is *pending* (30 s TTL);
  a terminal channel is retained 30 s so a late subscriber gets `end{done}` instead of
  hanging. Both cases are normal and constant — a Protect job finishes before the stream
  opens.
- Expose counts on `/health`: `{"status":"ok","jobs":N,"streams":M,"auth":"on"}`. This is
  the only telemetry the service has; a registry leak is otherwise invisible.

### A3. SSE endpoint — new `backend/app/routers/progress.py`

`GET /progress/{job_id}` (job id is 32 lowercase hex characters), a hand-rolled
`StreamingResponse` over an async generator — no new dependency. Headers `Cache-Control:
no-store`, `X-Accel-Buffering: no`.

Three frame types; `state` carries a **whole snapshot**, not a delta, so there are no
ordering or missed-frame bugs:

```
event: hello   data: {"job":"<id>"}
event: state   data: {"phase":"running","file":{"index":2,"total":5,"name":"report.pdf"},
                      "step":"Compressing","percent":42.5}
event: end     data: {"reason":"done"|"error"|"timeout"|"gone"}
```

A `: keep-alive` comment every 15 s so Traefik holds the connection. Caps: `MAX_STREAMS` 64
global, `MAX_STREAMS_PER_IP` 4.

### A4. Getting the job id to the service layer — header + `ContextVar`

A form field would mean a new parameter on 7 endpoint signatures **and** still not reach
`runner.run()`. Instead: client sends `X-Job-Id`; a FastAPI dependency validates it, calls
`registry.get_or_create`, sets a `ContextVar[Publisher]`, and returns the publisher.
Attached once per router at `include_router(..., dependencies=[...])`, so a future endpoint
cannot forget it.

ContextVar safety here is real but worth a comment and a direct test: FastAPI awaits `async
def` dependencies in the **same** asyncio Task as the endpoint, `CORSMiddleware` is
pure-ASGI (not `BaseHTTPMiddleware`, which would hop tasks), and `asyncio.to_thread` copies
the context. `progress.current()` returns a `NullPublisher` when no header was sent, so
services never branch on `None`.

### A5. Per-tool progress sources

| Tool | Source | Notes |
|---|---|---|
| **Compress** (gs) | Remove `-dQUIET` | stdout gives `Processing pages 1 through N.` then `Page 1`, `Page 2`… Parse both. gs writes the PDF to `-sOutputFile=`, so stdout is free. |
| **OCR** | **Keep `--quiet`**, add `--plugin app/tools/ocr_progress.py` | New shim implementing the `get_progressbar_class` hookimpl, emitting throttled JSON to **stderr**. The class deliberately ignores `disable=True` — OCRmyPDF forces it because our stderr is a pipe, which is exactly where we want machine-readable lines. Cap the OCR sub-step at 90%: `_pipeline.py` passes `progressbar_class=None` for the PDF/A tail, which therefore reports nothing. |
| **PDF→Word** | Instrument `app/tools/pdf2docx_cli.py` | Wrap the page parse/write loop with a counter, JSON to **stderr**. Same defensive try/except → warn and continue posture `_patch_spans()` already uses. Weight parse 0.8 / write 0.2. pdf2docx is not installed locally — confirm module paths inside the image first. |
| **PDF→Markdown** | `app/tools/anydoc_cli.py` → **stderr** | **Load-bearing:** `markdown.py::_parse` reads every JSON dict line off *stdout* and `to_markdown_one` indexes `lines[0]` positionally. A progress line on stdout would be read as file 0's status and break PDF→Markdown *for scanned documents only*. Belt and braces: also add a `"status" not in payload → skip` guard to `_parse`, plus a regression test. |
| Protect / Unlock / extract-images | file-level only | Fast enough that per-file granularity is the honest ceiling. |

**Compress weighting** — a fixed cursor over the maximum possible plan, assumed up front:

```
survey 5 | fonts 20 | verify 15 | rewrite 25 | ghostscript 35
```

Fast-forward through skipped steps rather than re-normalising. `wants_rewrite` /
`wants_ghostscript` are only known *after* the font pass, so re-normalising makes the bar
jump **backwards** — which reads as broken, where a forward jump reads as "that step was
quick". `streams.rebuild` and `fonts.subset` take an `on_step(done, total)` keyword
alongside the existing `deadline` keyword.

Honest about lumpiness: `rewrite` and `ghostscript` are genuinely smooth, and they are the
two that dominate (vector documents and scans respectively). `fonts` is lumpy — one 7 MB
emoji font is 95% of the step and one tick. Comment that in the code so nobody "fixes" it
later.

`on_step` fires on an `asyncio.to_thread` worker, so it must not touch the loop: capture
`asyncio.get_running_loop()` before the `to_thread` and use `loop.call_soon_threadsafe`,
throttled to 250 ms or 1% between publishes. One 20-file `/compress` request can spawn
~400 subprocesses; the throttle is what keeps the frame rate sane.

### A6. Queued state

A silent 60-second wait behind someone else's OCR is the worst-feeling state in the app
today. In `job_slot()`, publish `queued` when `_slots.locked()` (the check avoids a
one-frame flicker on the uncontended path), then `running` after acquire. UI copy: "Waiting
for a free slot — the server is busy". The existing 503 `server_busy` already has a
`MESSAGES` entry for the timeout case.

### A7. Frontend

**`components/tool/types.ts`** — grow `ToolRunContext` minimally with a
`setDetail(detail: string | null)` callback. A richer `report(patch)` object is tidier
greenfield, but keeping `setProgress`/`setStage` means the six browser-side tools (Merge,
Split, Rotate, Organize, Page Numbers, PDF→JPG page mode) need **zero edits**.

**`components/tool/processing-view.tsx`** — add a muted `detail` line under the stage
(`aria-live="polite"`) and an `onCancel` ghost button below the bar.

**`components/tool/backend-run.ts`** — extract a `createProgressBridge(ctx, { workingStage
})` so all six batched tools behave identically:

1. Generate a job id: `crypto.randomUUID()` with the dashes stripped.
2. Open the progress stream **before** `uploadAndProcess` (the terminal-TTL in A2 covers
   the POST-finishes-first case).
3. **Two phases, never blended.** Upload owns the bar 0→100 with stage "Uploading" — that
   percentage is real and the server cannot start until it lands. At 100, hand over to
   SSE-driven percentages and never hand back.
4. **Fallback.** If no `state` frame arrives within 2 s of the upload completing, do exactly
   what the code does today: `setProgress(null)` + `setStage(workingStage)`. If a frame
   arrives later, take over. The bar degrades, never breaks.
5. **Teardown.** Close on `end`, on abort, and in a `finally` around the upload. The bridge
   **never rejects** — the run's promise is the XHR alone, so a dead `/progress` route
   leaves every tool working exactly as today.

**`lib/api.ts`** — `uploadAndProcess` gains a `headers` option (for `X-Job-Id` and
`Authorization`); add a ~40-line `fetch`-based SSE frame reader.

**`components/tool/tool-shell.tsx`** — `handleCancel` aborts and resets to `idle`. **Note
the latent bug this exposes:** `handleSubmit`'s catch does `if (controller.signal.aborted)
return;` without changing phase. Today that only happens on unmount so nobody notices; wire
Cancel without resetting the phase yourself and the UI hangs on the spinner forever.

**Unlock** keeps its bespoke per-file loop — just move its position text from `setStage`
into `setDetail`.

---

## Part B — API protection

### B1. Token — compact HMAC, not JWT

No new dependency, no algorithm-confusion bug class, ~15 lines to verify.

```
v1.<b64url(payload)>.<b64url(hmac_sha256(secret, "v1." + payload))>
payload = {"exp":…, "nbf":…, "aud":"pdfkit-api", "jti":"<16 hex>"}
```

- **TTL 120 s**, `nbf` is 60 s in the past for skew. Checked only at request *start*, so a
  10-minute OCR begun at t=119 s is fine.
- **Not bound to IP** — mobile egress IPs change mid-session (CGNAT, Wi-Fi↔LTE), and Next
  and the backend derive the IP independently. A mismatch would be an unreproducible
  support nightmare. **Not bound to Origin** — CORS already enforces that for browsers, and
  a non-browser attacker sets any Origin it likes.
- `jti` is not checked server-side; a replay cache buys nothing against a 120 s TTL.
- **Rotation:** `API_TOKEN_SECRET` (mint + verify) plus `API_TOKEN_SECRET_PREVIOUS` (verify
  only).

### B2. Next mint route — new `frontend/app/api/token/route.ts`

`POST` (non-cacheable by construction, no cookies so no CSRF surface), `dynamic =
"force-dynamic"`, `runtime = "nodejs"`, `Cache-Control: no-store`.

Rate-limited via `lib/rate-limit.ts`, **which needs a small refactor** — it currently
hardcodes `prefix: "pdfkit:contact"` and `slidingWindow(5, "10 m")`. Change to a memoised
`getLimiter(name, limit, window)`; keep the fail-open behaviour (an Upstash outage must not
take the site down — unlimited minting is bounded by the backend's own per-IP limit, which
is the real ceiling). Suggested 30/min per IP.

**Fix the pre-existing bug while in there:** `app/api/contact/route.ts` takes the
*leftmost* `X-Forwarded-For` entry. Traefik *appends* to `X-Forwarded-For`, so the leftmost
entry is attacker-supplied — anyone can mint unlimited identities and bypass the
contact-form limiter entirely. Rightmost-untrusted is the correct parse.

**Client** — new `frontend/lib/token.ts`: module-level cache plus a single in-flight promise
so a 5-file run mints once; re-mint when the token has under 20 s left; on 401, clear, mint
once, retry **exactly once**, then surface `auth_invalid`. Put this in a shared
`withFreshToken(fn)` so `uploadWithPassword`'s retry loop inherits it.

### B3. Backend verification — `backend/app/main.py`

Router-level dependencies at include time, so a new endpoint on a protected router cannot
forget them:

```python
for router in PROTECTED_ROUTERS:
    app.include_router(router, dependencies=[
        Depends(coarse_rate_limit), Depends(require_token),
        Depends(job_rate_limit), Depends(job_publisher),
    ])
for router in OPEN_ROUTERS:
    app.include_router(router)
```

Order matters: coarse limit bounds an unauthenticated flood → auth is cheap and keeps
unauthenticated traffic out of the limiter's memory → job limit → publisher.

**Exemptions:** `/health` (Traefik and Coolify health checks cannot mint) and
`/ocr/languages` (the picker fetches it on page load before any run; it is a
process-lifetime-cached `tesseract --list-langs`, effectively static). **This requires
splitting `routers/ocr.py` into two `APIRouter` objects** — today `GET /ocr/languages` and
`POST /ocr` share one — and changing `routers/__init__.py` from a flat `ROUTERS` tuple to
`PROTECTED_ROUTERS` / `OPEN_ROUTERS`.

`/progress/{job_id}` **is** protected, which is only possible because we chose `fetch` over
`EventSource`.

| Condition | Status | `detail` |
|---|---|---|
| missing / malformed header | 401 | `auth_required` |
| expired | 401 | `auth_expired` |
| bad signature or wrong `aud` | 401 | `auth_invalid` |
| over limit | 429 | `rate_limited` + `Retry-After` |

Four matching `MESSAGES` entries in `frontend/lib/api.ts` — all inherit `recoverable: true`,
so they toast and return to the file list, matching existing behaviour.

### B4. Per-IP rate limiting — new `backend/app/services/ratelimit.py`

**First, fix the client IP.** Set `FORWARDED_ALLOW_IPS=172.16.0.0/12,10.0.0.0/8` (uvicorn
reads the env var) — the Docker bridge ranges Traefik comes from. Do **not** parse
`X-Forwarded-For` ourselves: uvicorn's `_TrustedHosts.get_trusted_client_address` already
walks the list right-to-left and returns the rightmost *untrusted* address, which is the
correct algorithm. Then just read `request.client.host`. The backend uses `expose:` not
`ports:`, so it is only reachable via Traefik on the internal network, which is what makes
a broad trusted range safe.

**Store:** in-process sliding window, `OrderedDict[str, deque[float]]`, pruned on access,
LRU-capped at 4096 IPs. Justified by `--workers 1` — which `_slots =
asyncio.Semaphore(...)` in `runner.py` **already** depends on, so this adds no new
constraint. Document both in one place. No Redis: the real concurrency ceiling is already
`MAX_CONCURRENT_JOBS=2`, and reset-on-restart is acceptable.

| Class | Limit |
|---|---|
| processing POSTs | 20/60 s **and** 120/3600 s |
| `/progress` | 60/60 s + 4 concurrent streams per IP |
| coarse, pre-auth | 240/60 s |
| `/health`, `/ocr/languages` | unlimited |

A real user doing 5-file batches makes 1–3 requests/min.

### B5. Config and deploy

New vars in `backend/app/config.py`, same plain-getenv style: `API_TOKEN_SECRET`,
`API_TOKEN_SECRET_PREVIOUS`, `API_TOKEN_TTL_SECONDS`, `API_TOKEN_SKEW_SECONDS`,
`API_TOKEN_AUDIENCE`, the `RATE_LIMIT_*` and `MAX_TRACKED_*` / `MAX_STREAMS*` / `PROGRESS_*`
values.

> **The gotcha that will cost an hour:** `auth.py` and `ratelimit.py` must do `from app
> import config` and read `config.API_TOKEN_SECRET` **at call time**. A `from app.config
> import API_TOKEN_SECRET` binds a copy at import and makes `monkeypatch` silently useless
> in tests.

`docker-compose.yml`: backend `environment:` gains the token, rate-limit and
`FORWARDED_ALLOW_IPS` vars; frontend `environment:` gains `API_TOKEN_SECRET` — **same
value, runtime env, never `NEXT_PUBLIC_`**. Add `API_TOKEN_SECRET=` to
`frontend/.env.example` and to the root `.env.example`. **Nothing new is a build arg**, so
rotating the secret never needs a frontend rebuild. Coolify: one shared `openssl rand -hex
32` plus `FORWARDED_ALLOW_IPS`.

---

## Sequencing

Each group is independently shippable and testable.

0. **Runner streaming** — `_spawn` rewrite + `on_line`. Zero user-visible change; suite must stay green. Ship alone.
1. **Registry + SSE + file-level events** — `progress.py`, `routers/progress.py`, the `job_publisher` dependency, publishes in the six service loops, queued state, `is_disconnected` checks.
2. **Intra-file percentage** — 2.1 gs (easiest, biggest document class) → 2.2 ocrmypdf plugin → 2.3 pdf2docx shim → 2.4 anydoc stderr + `_parse` guard → 2.5 compress weighting + `on_step` + the `call_soon_threadsafe` bridge. Each sub-step ships independently.
3. **Frontend progress + Cancel** — `setDetail`, `ProcessingView`, `handleCancel` + the phase-reset fix, `headers` option, SSE reader, the bridge, Unlock's detail text.
4. **Auth** — `auth.py`, `require_token`, router split, conftest, Next `/api/token`, `rate-limit.ts` refactor, `lib/token.ts`, `MESSAGES`.
5. **Backend rate limiting** — `ratelimit.py`, `client_ip`, `FORWARDED_ALLOW_IPS`, conftest reset fixture.
6. **Deploy** — compose env, `.env.example` files, Coolify vars, README/STATUS/CLAUDE.md (record the `workers=1` dependency and the "cost gate, not a security boundary" note).

## Tests

**What breaks and the fix:**

- **All 107 tests**, the moment auth is enforced. One-line fix in `conftest.py`'s `client`
  fixture — `TestClient` accepts `headers=`, so pass a minted `Authorization` and all 107
  then exercise the real auth path. **Also raise `API_TOKEN_TTL_SECONDS` for the suite** —
  this is not optional; a 120 s session-scoped token expires partway through a Docker run
  that includes OCR.
- **Rate limiting** — every test arrives from `client=("testclient", 50000)`, one IP, 107+
  requests. Add an autouse function-scoped `ratelimit.reset()` fixture.
- `test_password_handling.py`'s `run` spy takes `**kwargs`, so it absorbs the new `on_line`
  keyword. It is the only spy with a signature constraint.

**New:**

- `test_runner_streaming.py` — **highest value, needs no Docker tools** (drive `sys.executable -c`):
  capture is byte-identical to before; per-stream line ordering; **a child writing 1 MiB on
  both pipes does not deadlock** (the exact regression `communicate()` was protecting
  against); a 10 MiB line with no newline stays under the cap; timeout → 504 with the child
  reaped; carriage-return-separated output yields lines.
- `test_progress.py` — register-then-subscribe and subscribe-then-register; late subscriber
  gets the terminal snapshot; pending-TTL eviction; cap refusal degrades to `NullPublisher`;
  the `ContextVar` survives dependency → service → `to_thread`; registry is empty after N
  requests.
- `test_auth.py` — the four distinct 401 codes; `PREVIOUS`-secret token accepted; `/health`
  and `/ocr/languages` open.
- `test_rate_limit.py` — N+1 → 429 with `Retry-After`; different `client=` tuples
  independent; key derivation tested directly for the XFF-forgery case.
- `test_gs_progress.py` — 3-page compress sees `Page 1..3`. Ties the `-dQUIET` removal to a
  test so a future cleanup cannot silently kill progress.
- `test_ocr_plugin.py` — `ocrmypdf --plugin … --version` (cheap, proves it loads against
  the installed version) plus a real 2-page OCR asserting at least one progress line.
- `test_shims.py` — anydoc/pdf2docx progress goes to stderr and **anydoc stdout still
  parses as the existing status contract**.

Frontend has no test runner configured; don't invent one. Verification there is `npm run
lint`, `npx tsc --noEmit`, `npm run build`, and the manual matrix below.

## Risks and guards

| Risk | Guard |
|---|---|
| Runner deadlock or truncation turns every chatty tool into a 504 | Concurrent gather + the explicit 1-MiB-on-both-pipes test. Ship Group 0 alone. |
| ocrmypdf plugin fails to import → ocrmypdf exits non-zero → **OCR breaks entirely** (and it is also on the Word and Markdown paths) | Plugin never raises from `update`; the `--plugin … --version` test; pin the ocrmypdf major — the hook docstring warns reported events may change in minor releases. |
| Registry leak in a container that runs for weeks | Hard cap + TTL sweep on every touch + a test asserting it empties + `/health` reporting `jobs`/`streams`. |
| Auth silently off in production from one Coolify typo | Loud `logger.warning` at import, `"auth":"off"` in `/health`, and a deploy step that curls without a token and **expects 401**. |
| Limiter keyed on Traefik's IP → everyone shares one bucket → site 429s under mild load | `/health` echoes the observed client IP; one curl from a phone on mobile data proves it. Verify **before** turning limits down. |
| Cancel leaves the UI stuck on the spinner | `handleCancel` sets the phase itself (see A7). Test: cancel mid-OCR → file list intact. |
| SSE failure breaking a run | The bridge never rejects. Block `/progress` in devtools and confirm all seven tools behave as today. |
| A progress line on anydoc's **stdout** breaks PDF→Markdown for scanned documents only | stderr + the `_parse` guard + a regression test. |

## Verification

1. `docker compose --profile test run --rm backend-tests` → 107 + new, all green.
2. `docker compose up --build`; `curl localhost:8000/health` → `{"status":"ok","auth":"on","jobs":0,"streams":0,"client":"…"}`.
3. `curl -X POST localhost:8000/compress -F files=@sample.pdf` with no token → `401 auth_required`.
4. `curl -X POST localhost:3000/api/token` → `{token,expiresAt}`; 40× in a minute → 429.
5. Terminal A `curl -N -H "Authorization: Bearer $T" localhost:8000/progress/$JOB`; terminal B POSTs `/ocr` with 3 scanned PDFs and `-H "X-Job-Id: $JOB"`. Expect `hello`, optional `state{queued}`, `state` climbing through files 1–3, `end{done}`. Kill terminal A mid-run → the POST still returns the zip.
6. Browser: all 7 backend tools with 3 files each — "File 2 of 3 — x.pdf", a climbing intra-file bar, correct download. Compress once with a vector Print-To-PDF file (smooth rewrite ticks) and once with a scan (smooth gs page ticks). Uses the committed `frontend/test-fixtures/`.
7. Cancel mid-OCR → back to the file list, files intact, no error toast; re-run works; backend logs show the batch stopped early.
8. Kill the backend mid-run → existing `network_error` toast, not a stuck bar.
9. Block `/progress` in devtools → every tool works with today's indeterminate bar.
10. 25 compress POSTs in a minute → 429 `rate_limited`, UI shows the mapped sentence.
11. Two tabs starting OCR simultaneously plus a third → the third shows "Waiting for a free slot", then proceeds.
12. `npm run lint`, `npx tsc --noEmit`, `npm run build` clean.
13. Deploy to Coolify; repeat 3, 5, 6, 10 against `api.pdfkit.zeeshanai.cloud`; hit `/health` from a phone tether **and** from the VPS, confirming **two different** client IPs (proves proxy-headers).
14. Leave a progress stream open 10 minutes → keep-alives hold it through Traefik, no 502.

## Definition of done
Every backend tool shows file-level and intra-file progress with a working Cancel; the API
returns 401 without a token and 429 over the limit; the full backend suite plus the new
tests are green; frontend lint/typecheck/build clean; `STATUS.md` updated.
