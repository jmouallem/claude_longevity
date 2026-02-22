# Render Install / Replacement Guide

This runbook covers both:
- creating a **new Render project/service** from this repo, and
- replacing your current `n8n` service with this app (`claude_longevity`).

Target service:
- `https://dashboard.render.com/web/srv-d2d76abuibrs739auji0`

## Quick path: create a NEW project/service (recommended)

1. Push latest `main` (includes `render.yaml` Blueprint).
2. In Render dashboard, click `New` -> `Blueprint`.
3. Select repo: `jmouallem/claude_longevity`.
4. Render detects `render.yaml`; choose `Apply`.
5. Set required non-synced variables:
   - `ADMIN_PASSWORD`
   - `CORS_ORIGINS` (JSON array, include your final Render app URL, e.g. `["https://your-app.onrender.com"]`)
6. Deploy.
7. Verify `GET /api/health` is healthy.
8. Login and change admin password immediately.

## 1) Pre-cutover checklist

1. Confirm you are OK replacing the current running container (`n8n`) on this service.
2. If you need `n8n` data later, create a disk snapshot/backup first.
3. Confirm this repo is pushed to GitHub and Render can access it.

## 2) Replace service source with this repo

1. Open the service in Render:
   - `https://dashboard.render.com/web/srv-d2d76abuibrs739auji0`
2. Go to `Settings`.
3. Update service to deploy from this repository/branch:
   - Repo: `jmouallem/claude_longevity`
   - Branch: `main` (or your release branch)
4. Runtime:
   - Use `Docker` (the repo has a root `Dockerfile` that builds frontend + backend).
5. Root directory:
   - `/` (repo root).

## 3) Reuse disk for app data (SQLite/uploads)

If disk is already attached, keep it attached and set:
- Mount path: `/var/data`

Then set env vars so app writes to that disk:
- `DATA_DIR=/var/data`
- `UPLOAD_DIR=/var/data/uploads`
- `DATABASE_URL=sqlite:////var/data/longevity.db`

Notes:
- `sqlite:////var/data/longevity.db` is correct for absolute Linux path.
- Existing `n8n` files on disk will remain until manually removed.

## 4) Required Render environment variables

Set these in Render `Environment`:

Core:
- `ENVIRONMENT=production`
- `SECRET_KEY=<long-random-secret>`
- `ENCRYPTION_KEY=<long-random-secret>`
- `ADMIN_USERNAME=longadmin` (or your value)
- `ADMIN_PASSWORD=<strong-admin-password>`
- `AUTH_COOKIE_SECURE=true`
- `AUTH_COOKIE_SAMESITE=lax`

CORS / frontend origin:
- `CORS_ORIGINS=["https://<your-render-domain>"]`

Optional but recommended:
- `SECURITY_HEADERS_ENABLED=true`
- `ENABLE_PASSKEY_AUTH=true`
- `PASSKEY_RP_ID=<your-render-hostname-without-scheme>`
- `PASSKEY_ALLOWED_ORIGINS=["https://<your-render-domain>"]`

AI provider keys/models (as needed):
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` (if you use server-side keys)
- or configure keys from in-app settings per user.

## 5) Build/start details

No custom start command is required when using Docker; Render uses the repo `Dockerfile`.

The container runs:
- `uvicorn main:app --host 0.0.0.0 --port 8001`

Render will route external traffic to the service port.

Health check path:
- `/api/health`

## 6) Deploy

1. Click `Manual Deploy` -> `Deploy latest commit`.
2. Watch logs for:
   - app startup complete
   - no production security gate failures
   - successful health checks

## 7) Verify after deploy

1. Open app URL.
2. Register/login as user.
3. Login as admin with configured admin credentials.
4. Confirm persistence:
   - add profile data
   - restart deploy
   - data still present (verifies disk-backed SQLite).

## 8) Clean old n8n data from disk (optional)

After successful cutover and backup confirmation, you can remove old `n8n` files from the mounted disk.

Safe approach:
1. Temporarily shell into a one-off debug container with disk mounted, or
2. Use a maintenance release that removes only known `n8n` directories.

Do not delete blindly unless backup exists.

## 9) Rollback plan

If deployment fails:
1. In Render deploy history, rollback to previous successful `n8n` deploy.
2. Restore previous env vars if changed.
3. Re-verify health endpoint.

---

## Recommended production hardening

1. Rotate default admin password immediately after first login.
2. Use long random values for `SECRET_KEY` and `ENCRYPTION_KEY`.
3. Restrict `CORS_ORIGINS` to exact production domains only.
4. Keep disk snapshots enabled.
