# Phase 5 — Wire Backend Tools into the UI

## Goal
Connect the frontend to the Phase 4 backend: Compress, Protect, Unlock, OCR, and PDF-to-JPG's "Extract images" mode all become fully functional through the browser.

## Prerequisites
Phase 3 (all browser tools + shell) and Phase 4 (all backend endpoints, tested) both complete. Run `docker compose up backend` + `npm run dev` (frontend) together for this phase.

## Tasks

### 1. Backend client (`lib/api.ts`)
- `uploadAndProcess(endpoint, files, fields, { onProgress })` using `XMLHttpRequest` for real upload progress (fetch can't report upload progress). Returns `{ blob, filename, headers }`.
- Handles `422 {"detail":"password_required"}` specifically for Unlock — opens a per-file password dialog and retries the request with the password field set.
- Surfaces other error JSON (`{ detail }`) as toast notifications (sonner, already installed in Phase 0).
- Enforces the 50 MB client-side pre-check before upload (fast-fail without a round trip), matching backend's `MAX_UPLOAD_MB`.

### 2. Compress (`/compress-pdf`)
- `components/tools/compress/` — 3 radio cards: Extreme / Recommended (default) / Less.
- Wire to `POST /compress`. Result screen shows per-file "X% smaller" using the `X-Original-Size`/`X-Result-Size` response headers from Phase 4.

### 3. Protect (`/protect-pdf`)
- `components/tools/protect/` — password + repeat-password fields with show/hide toggles. CTA disabled until both are non-empty and match (matches iLovePDF's disabled-state screenshot).
- Wire to `POST /protect`.

### 4. Unlock (`/unlock-pdf`)
- `components/tools/unlock/` — callout "Just press the unlock button" (no password field shown up front).
- Wire to `POST /unlock` with no password first; on `password_required` response, show the per-file password dialog from `lib/api.ts`, retry; wrong password shows an inline error in that dialog rather than a generic toast.
- This is also the link target for the encrypted-PDF guard built in Phase 1 — verify that flow end-to-end now.

### 5. OCR (`/ocr-pdf`)
- `components/tools/ocr/` — multi-select of languages (max 3), populated from `GET /ocr/languages` at page load; info callout about accuracy expectations.
- Wire to `POST /ocr`.

### 6. PDF to JPG — extract-images mode (`/pdf-to-jpg`)
- Complete the mode built as a stub in Phase 3: wire "Extract images" to `POST /images/extract` with the existing quality toggle (normal/high).

### 7. Cross-cutting
- All 5 backend-bound tools use `ProcessingView`'s upload-progress bar (Phase 1) driven by real `onProgress` callbacks now, not a fake timer.
- Confirm the 50 MB dropzone limit (Phase 1) is actually enforced on these routes (browser-only tools don't need it).

## Verification
- With `docker compose up backend` and `npm run dev` running together, `NEXT_PUBLIC_API_URL=http://localhost:8000`:
  - Compress all three levels on the same file → extreme < recommended < less in size; each opens fine.
  - Protect with a password → resulting file prompts for a password in a PDF viewer.
  - Unlock that same file: with correct password → succeeds; with wrong password → inline error, no crash; via the Merge-tool encrypted-guard link → lands on Unlock with the file ready.
  - OCR the image-only fixture → resulting PDF has selectable/searchable text.
  - PDF→JPG extract-images on a PDF containing embedded images → ZIP contains them.
  - Kill the backend mid-request → frontend shows a clean error toast, not a hang or crash.
  - >50 MB file and non-PDF file are both rejected client-side with a clear message before any upload starts.
- `npm run lint && npm run build` clean.

## Definition of done
All 10 tools fully functional end-to-end in local dev (browser + Dockerized backend); `STATUS.md` updated — this marks feature-complete.
