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
   - `CORS_ORIGINS=https://pdfkit.zeeshanai.cloud` on the backend.
6. **Verify Traefik doesn't cap request bodies below 50 MB** — this is a known gotcha with Coolify's default Traefik config and will silently break large-file uploads to Compress/OCR/Protect/Unlock/Extract-images.
7. Trigger first deploy, confirm both containers come up healthy.
8. Update root `README.md` with the final deploy notes (domains, how to redeploy, where logs live).

## Verification
- `https://pdfkit.zeeshanai.cloud` loads the landing page over HTTPS with a valid cert.
- `https://api.pdfkit.zeeshanai.cloud/health` → `{"status":"ok"}` over HTTPS.
- Repeat the Compress and OCR checks from Phase 6's manual matrix against the **public** domain (this specifically exercises CORS and the Traefik body-size limit, which don't get tested locally).
- Push a trivial commit to the repo's default branch → confirm auto-deploy fires and the new build goes live without manual intervention.
- Check the VPS isn't newly disk-pressured after this deploy (`df -h /` per the standing Docker-cleanup-cron guidance) — 18+ other Coolify apps already share this box.

## Definition of done
App live and fully functional on both public domains; auto-deploy confirmed working; `STATUS.md` marked all phases complete.
