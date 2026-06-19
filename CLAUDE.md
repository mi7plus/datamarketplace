# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A two-sided data marketplace where **requesters** post data collection bounties and **providers** fulfil them by submitting datasets. Built with a Nuxt 4 frontend and a FastAPI backend connected to PostgreSQL.

---

Active roadmap: see datamarketplace-implementation-plan.md. Work it phase by phase.

Core design decision: requests are priced per unit against amount_required, budget-capped. Multiple/partial submissions and over-delivery all derive from this — don't reintroduce single-winner bounty assumptions.

## Running the Project

### Backend (FastAPI on port 3001)

From the project root on Windows:

```powershell
.\backend\run-backend.bat
```

Or on Mac/Linux:

```bash
./backend/run-backend.sh
```

Both scripts use the venv's Python directly (`venv/Scripts/python.exe -m uvicorn`) rather than a globally installed `uvicorn`, so the venv does **not** need to be activated first.

### Frontend (Nuxt on port 3000)

```bash
cd frontend
npm run dev
```

### Installing dependencies

```bash
# Backend
cd backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### Creating / migrating DB tables

There are no migration files — tables are created directly from SQLAlchemy models:

```powershell
& ".\backend\venv\Scripts\python.exe" -c "
import sys; sys.path.insert(0, 'backend')
from app.db import engine, Base
from app import models
Base.metadata.create_all(bind=engine)
"
```

---

## Architecture

### Backend (`backend/app/`)

| File | Purpose |
|---|---|
| `main.py` | FastAPI app factory; CORS middleware; router registration |
| `db.py` | SQLAlchemy engine + `SessionLocal`; `get_db` dependency |
| `models.py` | All ORM models (`UserAuth`, `DataRequest`, `Submission`, `UserProfile`, `UserAnalytics`) |
| `schemas.py` | Pydantic request/response schemas |
| `auth.py` | JWT issue/verify; `/auth/register`, `/auth/login`, `/auth/refresh` |
| `profile.py` | `/profile` — upsert and fetch `UserProfile` |
| `requests.py` | `/requests` — create and list `DataRequest` |
| `submissions.py` | `/submissions` — create `Submission` |

**Key design decisions:**
- All models inherit `BaseModel` which provides a UUID primary key, `created_at`, `updated_at`, `is_deleted`, and `version`.
- `.env` is loaded with an **absolute path** (`Path(__file__).resolve().parent.parent / ".env"`) in both `db.py` and `main.py` so the server starts correctly regardless of the working directory.
- `get_current_user` in `auth.py` is the shared dependency for authenticated routes — import it from there, not reimplemented elsewhere.
- `UserRole` and `SubmissionStatus` are Python `str` enums mapped to PostgreSQL enum columns.

**API prefix layout:**

```
/auth/*        → auth.py
/requests/*    → requests.py
/submissions/* → submissions.py
/profile/*     → profile.py
```

### Frontend (`frontend/`)

Nuxt 4 with Pinia state management and Tailwind CSS.

**`stores/auth.ts`** — central auth state. Persists the JWT access token in `localStorage`. All auth actions (`login`, `register`, `logout`) live here. Token refresh is handled via `/auth/refresh` (httpOnly cookie for the refresh token).

**`composables/useApi.ts`** — thin wrapper around `fetch` that injects the `Authorization: Bearer <token>` header automatically. Use `useApi().get(path)` / `useApi().post(path, body)` for all authenticated API calls instead of calling `$fetch` directly.

**`middleware/auth.ts`** — client-side route guard. Redirects unauthenticated users to `/login` for all routes except `/login` and `/register`.

**`nuxt.config.ts`** — `runtimeConfig.public.apiBase` defaults to `http://localhost:3001` and can be overridden with `NUXT_PUBLIC_API_BASE`.

**Page → role mapping:**
- `/requests` — browse open data requests (both roles)
- `/requests/create` — post a new data request (requester)
- `/requests/[id]` — view a single request and its submissions
- `/submissions` — provider's submission history
- `/profile` — edit `UserProfile` (firstName/lastName or companyName depending on `user_type`)

### Database

PostgreSQL. Connection string is built from five env vars: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` — all required; the app crashes on startup if any are missing/`None`.

---

## Environment Variables

### Backend (`.env` in `backend/`)

```
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
SECRET_KEY=
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_HOURS=2
FRONTEND_URL=http://localhost:3000
```

### Frontend

```
NUXT_PUBLIC_API_BASE=http://localhost:3001   # optional, this is the default
```

---

## Implementation Plan Progress

Active roadmap: `datamarketplace-implementation-plan.md`. Work phase by phase. See `PLAN_NOTES.md` for Phase 0 findings.

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Hygiene & bug fixes | ✅ Done | Secrets gitignored, bugs fixed, `routes.py` deleted |
| Phase 1 — Alembic + model + lifecycles | 🔜 Next | Set up Alembic before any further schema changes |
| Phase 2 — Structured request spec & creation flow | ⏳ Pending | |
| Phase 3 — Submission + ingest validation | ⏳ Pending | |
| Phase 4 — Fulfilment engine | ⏳ Pending | Core MVP value |
| Phase 5 — Escrow & payments (Stripe) | ⏳ Pending | |
| Phase 6 — Gated delivery (MinIO) | ⏳ Pending | |
| Phase 7 — Reputation & disputes | ⏳ Pending | |
| Phase 8 — GDPR & licensing | ⏳ Pending | |

## Known Gaps / TODOs

- `ProfileCreate` schema maps camelCase aliases (`firstName`, `lastName`, `companyName`) to snake_case DB columns; `email` is read from `UserAuth` (not stored on `UserProfile`).
- `requests.py` `list_requests` is unauthenticated (intentional — browsing is public).
- **Phase 1 is blocking** — do not use `Base.metadata.create_all` for further schema changes; Alembic must be set up first.
