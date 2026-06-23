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

### Running DB migrations (Alembic)

```powershell
# Apply all pending migrations
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head

# Check if models and DB are in sync
.\venv\Scripts\python.exe -m alembic check

# Create a new migration after a model change
.\venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe_change"
```

> **Important:** Always use Alembic for schema changes. Never use `Base.metadata.create_all` except on a fresh empty DB.
> For enum changes (adding values), hand-write `ALTER TYPE ... ADD VALUE IF NOT EXISTS` in the migration — autogenerate won't produce these.

### Seeding reference data

```powershell
cd backend
.\venv\Scripts\python.exe -m app.seed
```

### Running tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests/ -v
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
| `lifecycle.py` | State machine functions for `DataRequest` and `Submission` — all status changes go through here |
| `seed.py` | Seeds `licenses` table with standard license options — run once |
| `ingest.py` | CSV/JSONL validation engine: schema check, count, dedup, sample, SHA-256 hash |
| `storage.py` | Storage abstraction (`LocalStorage` now, `MinioStorage` in Phase 6) — `get_storage()` singleton; SSE-KMS on puts + transparent envelope encryption (E2/E5) |
| `crypto.py` | Envelope encryption for sensitive datasets (E5): `KmsKeyProvider` + `LocalKeyProvider` dev fallback behind `get_key_provider()`; AES-256-GCM `encrypt`/`decrypt`. See `KEY_MANAGEMENT.md` |
| `payments.py` | `PaymentProvider` ABC; `FakePaymentProvider` (default) + `StripePaymentProvider`; `append_ledger`; `ledger_balance`; `get_payment_provider()` singleton |
| `webhooks.py` | `POST /webhooks/stripe` — signature-verified Stripe webhook handler |
| `ingest_client.py` | Client + P1 SHADOW-compare harness for the Rust ingest service; `INGEST_SHADOW_ENABLED`/`INGEST_RUST_ENABLED` flags. See `../rust-ingest/` |
| `internal.py` | `POST /internal/ingest-result` — idempotent, token-gated callback the Rust workers POST to; Python stays the single writer to the core schema |

### Rust ingest service (`rust-ingest/`)

Standalone Rust service for heavy per-record + media work (validate/hash/dedup-hash/perceptual-hash), per `rowbound-rust-ingest-service-plan.md`. **Rust computes, Python settles** — it never writes money/lifecycle tables; it stages normalized key hashes to `submission_key_staging` (COPY) and returns a deterministic report. `keys.rs` is byte-parity with `app/keys.py` (golden vectors shared with `tests/test_rust_parity.py`). Deploy: `RUST_INGEST_DEPLOY.md`. **Not yet compiled** — see `rust-ingest/README.md`.

**Key design decisions:**
- All models inherit `BaseModel` which provides a UUID primary key, `created_at`, `updated_at`, `is_deleted`, and `version`.
- `.env` is loaded with an **absolute path** (`Path(__file__).resolve().parent.parent / ".env"`) in both `db.py` and `main.py` so the server starts correctly regardless of the working directory.
- `get_current_user` in `auth.py` is the shared dependency for authenticated routes — import it from there, not reimplemented elsewhere.
- `UserRole` and `SubmissionStatus` are Python `str` enums mapped to PostgreSQL enum columns.

**API prefix layout:**

```
/auth/*        → auth.py
/profile/*     → profile.py  (includes /stripe-connect, /stripe-status)
/requests/*    → requests.py  (includes /fund, /close, /ledger)
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
| Phase 1 — Alembic + model + lifecycles | ✅ Done | Alembic wired; models extended; state machines in `lifecycle.py`; 18 tests passing |
| Phase 2 — Structured request spec & creation flow | ✅ Done | Spec schema, column editor, live progress bar, real API in composable |
| Phase 3 — Submission + ingest validation | ✅ Done | File upload, CSV/JSONL validator, dedup, sample, SHA-256 hash; 31 tests passing |
| Phase 4 — Fulfilment engine | ✅ Done | `POST /submissions/{id}/accept` with `SELECT FOR UPDATE` + optimistic lock; `POST /{id}/reject`; expiry endpoint; buyer review UI with sample preview and accept/reject buttons; 40 tests passing |
| Phase 5 — Escrow & payments (Stripe) | ✅ Done | `FakePaymentProvider` + `StripePaymentProvider` behind `get_payment_provider()`; `POST /requests/{id}/fund` (DRAFT→OPEN + hold escrow); release on accept; refund on expire/close; `GET /requests/{id}/ledger`; Stripe Connect onboarding (`GET /profile/stripe-connect`); `POST /webhooks/stripe`; ledger invariant tests; 49 tests passing |
| Phase 6 — Gated delivery (MinIO) | ✅ Done | `MinioStorage` (private bucket, pre-signed URLs) + `LocalStorage` fallback in `storage.py`; `GET /submissions/{id}/download` (PAID-only gate); `GET /submissions/{id}/sample` (pre-payment preview); `DownloadButton.vue`; sample preview on provider history; 62 tests passing |
| Phase 7 — Reputation & disputes | ✅ Done | `Review` + `Dispute` models + migration; `POST /reviews/` (PAID-only, one per party per submission); `GET /reviews/user/{id}` (public); `POST /disputes/{id}/open` (buyer); `POST /disputes/{id}/resolve` (admin); `GET /disputes/` (admin queue); `UserAnalytics` reputation_score + transaction counters wired; `DisputeButton.vue`, `ReviewForm.vue`; reputation panel on profile; 75 tests passing |
| Phase 8 — GDPR & licensing | ✅ Done | Provider warranty checkboxes in `SubmissionForm.vue` (enforced server-side, stored in `owner_signature`); `POST /submissions/{id}/takedown` (admin, soft-delete + expire URL gate); `access_expiry` gate on download endpoint (410 Gone); `license_name` in `DataRequestResponseSchema` via `model_validate`; license shown on request detail; `terms.vue` + `privacy.vue` filled with GDPR-aware placeholder text; 84 tests passing |

## Known Gaps / TODOs

- `ProfileCreate` schema maps camelCase aliases (`firstName`, `lastName`, `companyName`) to snake_case DB columns; `email` is read from `UserAuth` (not stored on `UserProfile`).
- `requests.py` `list_requests` is unauthenticated (intentional — browsing is public).
- **Phase 1 is blocking** — do not use `Base.metadata.create_all` for further schema changes; Alembic must be set up first.
