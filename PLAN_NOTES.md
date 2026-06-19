# PLAN_NOTES.md — Phase 0 Findings

Generated as part of Phase 0 of `datamarketplace-implementation-plan.md`.

---

## Stack confirmed

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI + SQLAlchemy + PostgreSQL (port 3001) | Alembic not yet set up — tables created via `create_all` |
| Frontend | Nuxt 4 + Pinia + Tailwind CSS (port 3000) | |
| Storage | MinIO (S3-compatible, port 9000) | `boto3` in requirements but unused |
| Payments | Stripe | `stripe` in requirements but unused |

---

## Secrets

- Root `.env` was committed in the initial commit — added `.gitignore` and `.env.example` files; `backend/.env.example` added as well.
- Root `.env` Stripe keys were placeholder strings (`sk_test_...`), not real credentials — no rotation needed, but treat as a process reminder for when real keys are added.
- `.gitignore` now excludes `.env`, `backend/.env`, `__pycache__/`, `venv/`, `node_modules/`, `.nuxt/`.

---

## Bugs fixed (Phase 0)

| Bug | Fix |
|---|---|
| `submissions.py` hardcoded `provider_id=1` | Now uses `current_user.id` via `get_current_user` dependency |
| `submissions.py` set `accepted_amount=data.amount_provided` at creation | Field renamed to `offered_amount`; `accepted_amount` initialised to `0` (acceptance is Phase 4) |
| `schemas.py` `SubmissionCreateSchema.request_id: int` | Changed to `UUID`; field renamed from `amount_provided` to `offered_amount` |
| `requests.py` routes unauthenticated | Added `get_current_user`; `create_request` enforces `REQUESTER` role (403 for providers) |
| `routes.py` dead stub mounted nowhere | Deleted |
| `Submission` model missing `offered_amount` column | Added; applied via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |

---

## Schema conflicts with plan — resolutions

| Conflict | Resolution |
|---|---|
| Plan targets `offered_amount` on `Submission`; column didn't exist | Added in Phase 0 |
| Plan expects Alembic; repo uses `create_all` | Alembic setup is **Phase 1 Step 1.0** — do not use `create_all` for further schema changes |
| Root `.env` `DATABASE_URL` uses Docker Compose format; `backend/.env` uses individual vars | Two separate env contexts. Docker Compose uses root `.env`; uvicorn dev server uses `backend/.env`. Do not merge. |

---

## Role model note

`UserRole` (`REQUESTER | PROVIDER | ADMIN`) is baked into the account (`user_auth.role`). An account is a buyer **xor** a seller — a company that wants to do both would need two accounts. This is a known product limitation; leaving as-is for MVP per plan instructions.

---

## Phase 0 status: COMPLETE

Proceed to **Phase 1 — Alembic + model + lifecycles**.
