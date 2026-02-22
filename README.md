# Longevity Coach

AI-assisted longevity coaching app with:
- FastAPI backend
- React + Vite frontend
- SQLite storage
- Specialist-based orchestration
- Tool interfaces for standardized read/write/search operations

## Requirements
- Python 3.11+
- Node.js 20+
- npm

## Default Ports
- Frontend: `8050`
- Backend API: `8001`

## Environment Variables
Copy an example file to `.env` in the repo root and set values:
- Development: `.env.development.example`
- Production: `.env.production.example`
- Legacy/default template: `.env.example`

| Variable | Default | Required | Notes |
|---|---|---|---|
| `ENVIRONMENT` | `development` | No | Use `production`/`staging` to enforce secure startup checks. |
| `SECRET_KEY` | `change-me-in-production` | Yes | JWT signing key. Use a strong random value. |
| `ENCRYPTION_KEY` | `change-me-in-production-32bytes!` | Yes | Used to derive encryption key for stored API keys. |
| `DATABASE_URL` | `sqlite:///data/longevity.db` | No | SQLite by default. |
| `DATA_DIR` | `data` | No | Local data folder. |
| `UPLOAD_DIR` | `data/uploads` | No | Uploaded images folder. |
| `CORS_ORIGINS` | `["http://localhost:8050","http://localhost:8001"]` | No | Must be JSON array when set in `.env`. |
| `JWT_ALGORITHM` | `HS256` | No | JWT algorithm. |
| `JWT_EXPIRY_HOURS` | `72` | No | Access token lifetime. |
| `ADMIN_JWT_EXPIRY_HOURS` | `12` | No | Admin session JWT lifetime. |
| `AUTH_COOKIE_NAME` | `longevity_session` | No | HttpOnly session cookie name. |
| `AUTH_COOKIE_SECURE` | `false` | No | Must be `true` in production-like environments. |
| `AUTH_COOKIE_HTTPONLY` | `true` | No | Keep enabled to block JS access to session cookie. |
| `AUTH_COOKIE_SAMESITE` | `lax` | No | `strict`, `lax`, or `none` (requires secure). |
| `AUTH_COOKIE_DOMAIN` | unset | No | Optional cookie domain override. |
| `AUTH_COOKIE_PATH` | `/` | No | Cookie path scope. |
| `SECURITY_HEADERS_ENABLED` | `true` | No | Enables CSP/XFO/nosniff/referrer/permissions headers. |
| `SECURITY_CSP` | set in config | No | Override default Content-Security-Policy if needed. |
| `RATE_LIMIT_AUTH_LOGIN_ATTEMPTS` | `10` | No | Max login attempts per window. |
| `RATE_LIMIT_AUTH_LOGIN_WINDOW_SECONDS` | `300` | No | Login rate limit window. |
| `RATE_LIMIT_AUTH_REGISTER_ATTEMPTS` | `5` | No | Max register attempts per window. |
| `RATE_LIMIT_AUTH_REGISTER_WINDOW_SECONDS` | `600` | No | Register rate limit window. |
| `RATE_LIMIT_CHAT_MESSAGES` | `30` | No | Max chat requests per window. |
| `RATE_LIMIT_CHAT_WINDOW_SECONDS` | `60` | No | Chat rate limit window. |
| `ENABLE_WEB_SEARCH` | `true` | No | Enables Phase C web search tool. |
| `WEB_SEARCH_ALLOWED_SPECIALISTS` | `["orchestrator","nutritionist","supplement_auditor","safety_clinician","movement_coach","sleep_expert"]` | No | JSON array. Specialists allowed to call web search. |
| `WEB_SEARCH_MAX_RESULTS` | `5` | No | Max web results per query (capped in code). |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `8` | No | Per-provider timeout. |
| `WEB_SEARCH_CACHE_TTL_HOURS` | `12` | No | Web search cache expiry window. |
| `WEB_SEARCH_CIRCUIT_FAIL_THRESHOLD` | `3` | No | Consecutive provider failures before circuit opens. |
| `WEB_SEARCH_CIRCUIT_OPEN_SECONDS` | `60` | No | Circuit open time before retry. |

## Local Setup

### 1) Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### 2) Frontend
```powershell
cd frontend
npm ci
npm run dev -- --port 8050
```

Open:
- `https://localhost:8050` (Vite dev HTTPS via `@vitejs/plugin-basic-ssl`)
- API health: `http://localhost:8001/api/health`

Auth/session note:
- Frontend uses secure cookie-backed sessions (`credentials: include`) and no longer stores auth token in local storage.

Manual stop:
- In each terminal window, press `Ctrl+C`.

## Start/Stop with VS Code Tasks
Configured tasks in `.vscode/tasks.json`:
- `Start Backend`
- `Start Frontend`
- `Start Full Stack`

Run:
1. `Ctrl+Shift+P`
2. `Tasks: Run Task`
3. Choose `Start Full Stack`

Stop:
1. `Ctrl+Shift+P`
2. `Tasks: Terminate Task`
3. Select running task(s), or choose `Terminate All Tasks`

## Docker
Build and run:
```powershell
docker compose up --build -d
```

Stop:
```powershell
docker compose down
```

Container exposes backend on `8001` and serves built frontend static assets from backend.

## Data & Persistence
- SQLite DB: `backend/data/longevity.db` (local dev from `backend` cwd)
- Uploads: `backend/data/uploads`
- Docker volume maps `./data` into container at `/app/data`

## Tool Interfaces (Phase A/B/C)
Implemented tool registry in `backend/tools/` with standardized interfaces for:
- Profile read/patch
- Medication/supplement resolve + upsert
- Checklist marking
- Goal upsert
- Exercise/vitals write
- Meal template list/resolve/upsert + log from template
- Notifications create/list/mark-read
- Health history search
- Web search with cache

This provides consistent read/write behavior for orchestrator and specialists.

## Common Commands
Backend lint-free compile check:
```powershell
python -m compileall backend
```

Frontend production build:
```powershell
cd frontend
npm run build
```

Security dependency audit checks:
```powershell
python -m pip install pip-audit
python -m pip-audit -r backend/requirements.txt
cd frontend
npm audit --omit=dev --audit-level=high
```

## Troubleshooting
- Intake Coach not showing after code changes:
  - Restart backend and hard refresh browser (`Ctrl+F5`).
  - Verify `GET /api/specialists` includes `intake_coach`.
- Mic/camera permission issues on mobile:
  - Use `https://localhost:8050`.
  - Accept local dev certificate.
- Wrong instance running:
  - Confirm backend started from this repo path.
