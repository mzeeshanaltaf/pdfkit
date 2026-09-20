# Phase 7 — Deploy to Coolify

## Goal
PDFKit live on the Hostinger VPS behind Coolify, both services healthy, with subdomains and env vars wired correctly.

## Prerequisites
Phase 6 complete — app fully polished and passing the full local manual matrix.

## Tasks
1. Push the repo to GitHub (create the repo if it doesn't exist yet).
2. Use the **`add-app-to-coolify`** skill to drive the deploy — it already knows how to create the app from a GitHub repo, set env vars, attach domains with Let's Encrypt, and wire auto-deploy on push. Don't hand-roll these steps.
3. Add as a **Docker Compose** resource in Coolify pointing at the repo's `docker-compose.yml`.
4. Domains:
   - `pdfkit.zeeshanai.cloud` → `frontend:3000`
   - `api.pdfkit.zeeshanai.cloud` → `backend:8000`
5. Env vars in Coolify:
   - `NEXT_PUBLIC_API_URL=https://api.pdfkit.zeeshanai.cloud` (build-time — frontend must be rebuilt if this changes).
   - `NEXT_PUBLIC_SITE_URL=https://pdfkit.zeeshanai.cloud` (build-time, inlined like the one above — **not currently wired into `docker-compose.yml`'s frontend `build.args`**, only `NEXT_PUBLIC_API_URL` is, so add it there first. Left unset it silently falls back to `http://localhost:3000` and every canonical URL, OG URL, sitemap entry and `llms.txt` link ships pointing at localhost — this was flagged as an open item coming out of the SEO pass).
   - `CORS_ORIGINS=https://pdfkit.zeeshanai.cloud` on the backend.
   - Contact form (runtime, already read via `docker-compose.yml`'s frontend `environment:` block, so only need setting in Coolify, not in the compose file): `N8N_CONTACT_WEBHOOK_URL`, `N8N_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`. All four are optional in the sense that the app still runs without them (missing webhook config no-ops the route, missing Upstash creds make the rate limiter fail open) — but `/contact` silently won't deliver mail until the first two are set.
6. **Verify Traefik doesn't cap request bodies below 50 MB** — this is a known gotcha with Coolify's default Traefik config and will silently break large-file uploads to Compress/OCR/Protect/Unlock/Extract-images/PDF-to-Word/PDF-to-Markdown.
7. **Verify the proxy's read/idle timeout clears the longest job.** PDF to Word with OCR runs two subprocesses back to back — recognition (`OCR_TIMEOUT_SECONDS`, 600) then layout rebuilding (`WORD_TIMEOUT_SECONDS`, 300) — so a long scan can hold one request open for many minutes with no bytes flowing. A proxy that gives up first turns that into a "Could not reach the server" toast with no server-side error to find. Either raise the timeout or lower the two backend ones so the server is always the thing that gives up first, with a `504 processing_timed_out` the UI already knows how to show.
8. **Confirm the backend's tmpfs mount survives Coolify's compose handling.** `docker-compose.yml`'s `backend` service mounts `/tmp/pdfkit` with explicit `uid=1001,gid=1001,mode=0700` because a bare tmpfs mount masks the image's chown and every upload fails with `PermissionError` otherwise (found and fixed in Phase 4). The options are already committed in the repo's compose file, so nothing to author here — just verify after first deploy that Coolify didn't strip the mount options (upload a file to Compress/OCR and confirm it doesn't 500).
9. Trigger first deploy, confirm both containers come up healthy.
10. Create the root `README.md` (doesn't exist yet — only `frontend/README.md` does) with the final deploy notes (domains, how to redeploy, where logs live).

## Verification
- `https://pdfkit.zeeshanai.cloud` loads the landing page over HTTPS with a valid cert.
- `https://api.pdfkit.zeeshanai.cloud/health` → `{"status":"ok"}` over HTTPS.
- `view-source:` on the homepage and a tool page: canonical, OG URL and sitemap entries resolve to `pdfkit.zeeshanai.cloud`, not `localhost:3000` — confirms `NEXT_PUBLIC_SITE_URL` actually took at build time.
- Repeat the Compress and OCR checks from Phase 6's manual matrix against the **public** domain (this specifically exercises CORS and the Traefik body-size limit, which don't get tested locally). Also run one PDF to Word conversion with `ocr=auto` against `sample-scanned.pdf` — the one job that can legitimately hold a request open for minutes, and the one the proxy-timeout check in task 7 is protecting against.
- Submit `/contact` once for real and confirm the n8n webhook receives it, or confirm the vars are deliberately left unset and the route no-ops cleanly.
- Push a trivial commit to the repo's default branch → confirm auto-deploy fires and the new build goes live without manual intervention.
- Check the VPS isn't newly disk-pressured after this deploy (`df -h /` per the standing Docker-cleanup-cron guidance) — 18+ other Coolify apps already share this box, and the backend image grew to ~1.27 GB after the OCR language expansion.

## Definition of done
App live and fully functional on both public domains; auto-deploy confirmed working; `STATUS.md` marked all phases complete.
