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
Copy `.env.example` to `.env` in the repo root and set values.

| Variable | Default | Required | Notes |
|---|---|---|---|
| `SECRET_KEY` | `change-me-in-production` | Yes | JWT signing key. Use a strong random value. |
| `ENCRYPTION_KEY` | `change-me-in-production-32bytes!` | Yes | Used to derive encryption key for stored API keys. |
| `DATABASE_URL` | `sqlite:///data/longevity.db` | No | SQLite by default. |
| `DATA_DIR` | `data` | No | Local data folder. |
| `UPLOAD_DIR` | `data/uploads` | No | Uploaded images folder. |
| `CORS_ORIGINS` | `["http://localhost:8050","http://localhost:8001"]` | No | Must be JSON array when set in `.env`. |
| `JWT_ALGORITHM` | `HS256` | No | JWT algorithm. |
| `JWT_EXPIRY_HOURS` | `72` | No | Access token lifetime. |
| `ENABLE_WEB_SEARCH` | `true` | No | Enables Phase C web search tool. |
| `WEB_SEARCH_ALLOWED_SPECIALISTS` | `["orchestrator","nutritionist","supplement_auditor","safety_clinician","movement_coach","sleep_expert"]` | No | JSON array. Specialists allowed to call web search. |
| `WEB_SEARCH_MAX_RESULTS` | `5` | No | Max web results per query (capped in code). |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `8` | No | Per-provider timeout. |
| `WEB_SEARCH_CACHE_TTL_HOURS` | `12` | No | Web search cache expiry window. |

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

## Troubleshooting
- Intake Coach not showing after code changes:
  - Restart backend and hard refresh browser (`Ctrl+F5`).
  - Verify `GET /api/specialists` includes `intake_coach`.
- Mic/camera permission issues on mobile:
  - Use `https://localhost:8050`.
  - Accept local dev certificate.
- Wrong instance running:
  - Confirm backend started from this repo path.
