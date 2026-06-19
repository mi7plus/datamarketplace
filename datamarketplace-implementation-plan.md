# Data Marketplace — MVP Implementation Plan

**Audience:** Claude Code (agentic, step-by-step execution)
**Repo:** `mi7plus/datamarketplace`
**Stack (confirmed from repo):** FastAPI + SQLAlchemy + PostgreSQL backend (port **3001**) · Nuxt 4 + Pinia + Tailwind frontend (port **3000**) · MinIO (S3-compatible) · Stripe · Docker Compose. `boto3` and `stripe` are already in `requirements.txt` but **unused**.
**Goal:** Turn the existing CRUD scaffold (register, post requests, submit data, browse) into a working *transactional* marketplace whose core loop is: **post a structured data request → multiple providers fulfil it partially → funds change hands safely per accepted unit.**

---

## How to use this document

Work **phase by phase, top to bottom**. Each phase has a **Goal**, **Steps** (concrete deliverables, with real file paths from this repo), **Acceptance criteria**, and **Decisions** already made for the MVP — don't re-litigate those.

Rules of engagement:

1. **Read before you write.** Finish Phase 0 and report findings before any feature code.
2. **One phase = one or more small commits.** Never bundle a migration with unrelated UI. Each commit leaves the app runnable.
3. **Migrations are sacred.** Never auto-run a destructive migration. Generate, show, pause for human confirmation.
4. **Don't gold-plate.** If it's in "Explicitly out of scope," don't build it — leave a TODO.
5. **Stay on the existing stack.** FastAPI/SQLAlchemy/Nuxt/Pinia/MinIO/Stripe. Do not introduce a new framework, ORM, or language.
6. **Test the state machine, not the happy path.** The money/fulfilment transitions are where the bugs and the value are.

---

## The one design decision everything depends on

The hard requirements — *multiple submissions per request, partial submissions, and submissions that deliver more than requested* — are not three features. They're three consequences of one choice: **how a request defines "enough," and how money maps to delivered data.**

**Decision: requests are priced per unit, against a target quantity, with a budget cap.**

Your `DataRequest` already has `amount_required` (Integer) and `budget` (Float). Read those as **target quantity** and **total budget**, and derive (or store) `price_per_unit = budget / amount_required`. Each accepted submission is paid `accepted_amount × price_per_unit`; the buyer can never spend more than `budget`, which is escrowed up front. This single choice dissolves most hard cases:

- **Multiple submissions** → sum `accepted_amount` across submissions toward `amount_required`.
- **Partial submission** → a submission whose `accepted_amount < amount_required`; the normal case, nothing special. (`Submission.accepted_amount` already exists for exactly this.)
- **Under-delivery / expiry with the target unmet** → a non-event: buyer only paid for accepted units; unspent escrow refunds on close.
- **Pooled / kickstarter funding** → multiple backers contributing to one `budget`; mechanically one escrow balance.

That leaves exactly **one** case needing real logic: **over-delivery** — a submission offering more units than the request still needs — handled by *capping at acceptance time* against live remaining capacity (Phase 4).

Keep a secondary `fixed_bounty` mode for simple "one dataset, one winner" requests, but **per-unit is the primary path** and the rest of this plan assumes it. If the team rejects per-unit as the primitive, **stop and escalate** — most tables and transitions below change.

---

## Phase 0 — Orientation, hygiene, and known-bug cleanup (read-mostly)

**Goal:** Confirm the lay of the land, fix the small landmines already flagged in `CLAUDE.md`, and secure the leaked secrets — before building features on top.

### Steps

1. **Rotate and ignore secrets.** A `.env` with `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` is committed at repo root. Treat them as compromised: rotate in the Stripe dashboard, add `.env` (root and `backend/.env`) to `.gitignore`, and provide a `.env.example` with empty values. Do **not** commit real keys again. *(This is the first action — do it before anything else.)*
2. **Fix the known bugs listed in `CLAUDE.md` and visible in the routers** (small, isolated commits):
   - `app/submissions.py` hardcodes `provider_id=1` (an int, but the column is UUID) — replace with `current_user.id` via the shared `get_current_user` dependency from `app/auth.py`.
   - `app/submissions.py` `create_submission` sets `accepted_amount=data.amount_provided` at creation — **wrong**: a freshly submitted dataset has `accepted_amount = 0`. Acceptance is the buyer's later act (Phase 4). Rename the inbound field to `offered_amount`.
   - `app/schemas.py` `SubmissionCreateSchema.request_id: int` and `DataRequest` ids are UUID — fix the type to `UUID`/`str`.
   - `app/requests.py` routes are unauthenticated — add `get_current_user`; enforce that only `REQUESTER`-role users create requests.
   - `app/routes.py` is a dead stub not mounted in `main.py` — delete it or clearly mark it, so it isn't confused with the live routers.
3. **Note the role model.** `UserRole` is `REQUESTER | PROVIDER | ADMIN` baked into the **account** (`user_auth.role`), while individual-vs-company is `UserProfile.user_type` (`person|company`). So an account is a buyer **xor** a seller, not both. Flag this as a product question (a company may want to do both) — for the MVP, leave it as-is but document it.
4. **Produce `PLAN_NOTES.md`** at repo root: confirm the stack, list the bugs fixed, and record any place where this plan's target schema conflicts with reality, with a one-line resolution each. **Surface this before starting Phase 1.**

### Acceptance criteria

- `.env` no longer tracked by git; keys rotated; `.env.example` present.
- The four router bugs are fixed; `create_submission` uses the authenticated provider and stores `offered_amount` with `accepted_amount = 0`.
- App still runs (`backend/run-backend.*` + `npm run dev`) and existing flows work.

---

## Phase 1 — Migrations, data model & lifecycle state machines

**Goal:** Establish a real migration path and the schema spine, and model the two lifecycles explicitly. This is the most important phase — get the model right and the features are wiring.

### Step 1.0 — Add Alembic (blocking, do this first)

The repo creates tables via `Base.metadata.create_all`, which **does not** alter existing tables or add enum values. This plan adds columns and new enum members to live tables, so:

- Add **Alembic**, point it at `app.db:Base` / `DATABASE_URL`, and autogenerate an **initial baseline** migration matching the current models.
- From here on, **every model change ships with an Alembic migration**. Update `CLAUDE.md`'s "Creating / migrating DB tables" section accordingly.
- Note for enum changes: Postgres enums need explicit `ALTER TYPE ... ADD VALUE` (autogenerate won't always produce these) — write those by hand in the migration.

### Target model changes

Extend the existing models (`app/models.py`); reuse existing columns — **do not duplicate** what's already there.

**`DataRequest`** (currently: `title, description, required_format, amount_required, budget, status, requester_id`). Add:
- `pricing_mode` enum (`per_unit | fixed_bounty`), default `per_unit`
- `unit` (`row | record | image | …`)
- `price_per_unit` (Float) — or compute from `budget / amount_required` and store for stability
- `deadline` (DateTime) — needed for expiry
- `license_id` (FK → new `licenses`)
- `spec` — structured schema (JSON column, or child `request_specs` table; Phase 2)
- `accepted_total` (Integer, default 0) — running sum of accepted units; **or** derive from submissions. Pick one and be consistent. (Storing it makes the Phase 4 lock simpler.)
- Reuse existing `amount_required` as **target quantity**.

**`RequestStatus`** (currently `DRAFT, OPEN, REVIEW, COMPLETED, EXPIRED`). Add **`PARTIALLY_FULFILLED`**. Map meanings: `COMPLETED` = fully fulfilled; `EXPIRED` = closed under-filled. Keep `REVIEW` if you want a buyer-review gate.

**`Submission`** (already rich: `accepted_amount, content_link, quality_score, verified, dataset_hash, access_token_id, download_limit, verified_by, review_notes, file_size_bytes, mime_type, storage_location, owner_signature, access_expiry`). Add:
- `offered_amount` (Integer) — what the provider claims (set at submit)
- `validated_amount` (Integer) — units passing ingest validation (Phase 3)
- `amount_due` (Float) — `accepted_amount × price_per_unit`, set at acceptance
- `validation_report` (JSON)
- **Reuse** `accepted_amount` (already there — partial-ready), `storage_location` / `dataset_hash` / `access_token_id` / `access_expiry` / `download_limit` / `owner_signature` (Phase 6), `verified` / `verified_by` / `review_notes` / `quality_score` (review).

**`SubmissionStatus`** (currently `PENDING, ACCEPTED, REJECTED`). Add: **`VALIDATED`, `PARTIALLY_ACCEPTED`, `PAID`, `DISPUTED`**, plus `REJECTED_INVALID` (failed validation) if you want to distinguish from buyer-rejected.

**New tables:**
- `licenses` — `id, name, terms`. Seed 3–4 standard options.
- `ledger` (escrow; Phase 5) — append-only: `id, request_id, submission_id?, type (hold|release|refund), amount, external_ref, created_at`. Derive balances by summing; prefer this over mutable balance columns.
- `disputes` (Phase 7) — `id, submission_id, status, reason, notes`.
- `reviews` (Phase 7) — `id, subject_user_id, author_id, request_id, rating, comment`. (Aggregate into the existing **`UserAnalytics`** table — `reputation_score`, `total_transactions`, `successful_transactions` are already there.)

### Lifecycle — `DataRequest`

```
DRAFT ──(buyer funds escrow)──► OPEN
OPEN ──(first acceptance, target not yet met)──► PARTIALLY_FULFILLED
PARTIALLY_FULFILLED ──(more accepted)──► PARTIALLY_FULFILLED   (loop)
OPEN | PARTIALLY_FULFILLED ──(accepted_total == amount_required)──► COMPLETED
OPEN | PARTIALLY_FULFILLED ──(deadline passes, target unmet)──► EXPIRED   (closed under-filled)
non-terminal, no acceptances ──(buyer cancels)──► EXPIRED/cancelled
```
On `COMPLETED` / `EXPIRED` / cancel: refund unspent escrow.

### Lifecycle — `Submission`

```
PENDING ──(ingest validation)──► VALIDATED | REJECTED_INVALID
VALIDATED ──(buyer/auto review + allocation)──► ACCEPTED | PARTIALLY_ACCEPTED | REJECTED
ACCEPTED | PARTIALLY_ACCEPTED ──(escrow release)──► PAID
ACCEPTED | PARTIALLY_ACCEPTED ──(buyer disputes in window)──► DISPUTED
DISPUTED ──(resolution)──► PAID | REJECTED(refunded)
```
`PARTIALLY_ACCEPTED` is the over-delivery case: validated 8,000, only 3,000 still needed → accept 3,000, pay 3,000, surplus 5,000 not purchased (provider keeps it; not delivered).

### Steps

1. Alembic baseline (Step 1.0).
2. Migrations for the column/enum additions above (hand-write the `ALTER TYPE ... ADD VALUE` for enums).
3. Implement both state machines as **explicit code** — a transitions map + one function per entity that validates current state and records the change. No scattered booleans.
4. Add invariant guards (asserted in code + enforced in the Phase 4 transaction): `accepted_amount ≤ validated_amount`, and `sum(accepted_amount for a request) ≤ amount_required`.
5. Seed `licenses` (placeholder wording is fine).

### Acceptance criteria

- Alembic migrates forward and rolls back cleanly on a fresh Postgres.
- A test exercises every defined transition and rejects undefined ones.
- Invariant guards covered by tests (accepting more than validated fails).

---

## Phase 2 — Structured request spec & creation flow

**Goal:** Replace the free-text-ish request (`title, description, required_format`) with a machine-readable spec, because validation, partial fulfilment, over-delivery, and dedup all need something to measure against.

### The spec captures
- **Schema:** ordered columns, each `name`/`type`/`required`.
- **Unique key** (optional, encouraged): column(s) uniquely identifying a record — the lever for cross-provider dedup (Phase 4). No key → dedup disabled for that request, with a buyer-beware note.
- **Quantity:** `unit` + `amount_required` (existing).
- **Coverage (optional):** when "enough" is *which* records, not just how many — `coverage_unit` + `coverage_set` (e.g. regions/SKUs/dates). *If too complex for v1, ship quantity-only but leave the column nullable.*
- **Format:** start with **CSV / JSONL only** (replaces free-text `required_format`).
- **Freshness** (optional), **pricing** (`pricing_mode`, `price_per_unit`/`budget`), **license** (seeded).
- **Provider warranties** (affirmed later at submit): right to sell/share; no unconsented personal data / properly anonymized (Phase 8).

### Steps
1. Extend `app/schemas.py` `DataRequestCreateSchema` and the `frontend/components/requests/RequestForm.vue` + `frontend/pages/requests/create.vue` to capture the spec (a schema-column editor: add/remove rows of name+type+required). Keep it boring.
2. Validate server-side: ≥1 column; if `per_unit`, `price_per_unit` and `amount_required` required and positive; `budget` derived, not free-entered (or validated to equal `price_per_unit × amount_required`).
3. Persist the spec (JSON column / child table per Phase 1).
4. Update `frontend/pages/requests/[id].vue` to render the spec **and live fulfilment state**: `accepted_total / amount_required`, **remaining capacity**, deadline, submissions list. *Remaining-capacity display is the single biggest over-delivery preventer — providers self-limit when they see how much is left.*
5. Update `frontend/pages/requests/index.vue` + `RequestCard.vue` with a progress indicator and filters (open vs completed, unit type).

### Acceptance criteria
- A request created via the UI persists a complete, valid spec.
- `[id].vue` shows remaining capacity, updating as submissions are accepted (verify after Phase 4).
- Invalid specs rejected with field-level errors.

---

## Phase 3 — Submission flow with ingest-time validation

**Goal:** On submit, the platform *measures* the dataset against the request spec — what makes partial/over/dedup tractable instead of guesswork.

### Steps
1. Rework `frontend/components/requests/SubmissionForm.vue` + `app/submissions.py`: provider uploads a file (to MinIO — Phase 6) + affirms warranties + declares `offered_amount`. Use the authenticated provider (Phase 0 fix).
2. Run **ingest validation** server-side → `validation_report` (JSON):
   - **Schema check:** required columns present and type-parseable. Extra columns allowed (record that it's a superset).
   - **Quantity:** count conforming records → `validated_amount`.
   - **Key uniqueness (if key declared):** within-submission dupes don't count toward `validated_amount`.
   - **Coverage (if declared):** record covered `coverage_set` values; out-of-scope records don't count (flag, don't pay).
   - **Sample extraction:** carve a small preview (first N rows + schema) → store separately; buyer sees this pre-payment, never the full file.
   - **Hashing:** populate the existing `dataset_hash` for integrity/dedup.
3. Store the full file in MinIO; set `storage_location`, `file_size_bytes`, `mime_type` (all existing fields). Do **not** make it buyer-downloadable yet.
4. Set `status = VALIDATED` (or `REJECTED_INVALID`); surface the report to the provider for re-submission.

### "More data than requested" — three flavors, decided here
- **More rows than needed** → quantity over-delivery; capped at acceptance (Phase 4). Here just record true `validated_amount`.
- **More columns than spec** → allowed; record the superset. MVP default: deliver the full file (note it); stripping-to-spec is deferred.
- **Rows outside coverage** → don't count toward fulfilment; flagged; not paid.

### Acceptance criteria
- A conforming CSV yields a correct `validated_amount` + sample + `dataset_hash`.
- Missing/mistyped columns flagged precisely.
- With a declared key, within-submission dupes excluded from `validated_amount`.
- Full file unreachable by the buyer at this stage (verify the gate).

---

## Phase 4 — Fulfilment engine (the heart of the MVP)

**Goal:** Turn validated submissions into accepted, paid units, allocating against live remaining capacity, multi-provider and over-delivery handled deterministically and race-safely.

### Allocation algorithm (at acceptance, inside ONE DB transaction)

```
BEGIN TRANSACTION (lock the data_requests row; use the existing `version` column for optimistic concurrency)
  remaining = amount_required − accepted_total(request)
  eligible  = validated_amount(submission)
  IF key declared:
      eligible -= overlap(submission keys, already-accepted keys for this request)   # dedup via dataset contents
  accepted = min(eligible, remaining)
  amount_due = accepted × price_per_unit
  IF accepted == 0:                 submission.status = REJECTED
  ELIF accepted < offered_amount:   submission.status = PARTIALLY_ACCEPTED
  ELSE:                             submission.status = ACCEPTED
  submission.accepted_amount = accepted
  submission.amount_due = amount_due
  request.accepted_total += accepted
  request.status = COMPLETED if accepted_total == amount_required else PARTIALLY_FULFILLED
COMMIT
```
Then trigger escrow release for `amount_due` (Phase 5) and unlock delivery (Phase 6).

### Why each piece matters
- **`min(eligible, remaining)`** is the over-delivery cap → `PARTIALLY_ACCEPTED`, surplus not purchased.
- **Transaction + `version` lock** is non-negotiable. Two providers racing for the last 1,000 units without it → both accepted, budget blown. **This is the likeliest money bug — comment it loudly and test it.**
- **Overlap subtraction (dedup)** stops paying two providers for the same record. No declared key → skip, rely on provider warranty + buyer-beware note (acceptable MVP limitation).

### Acceptance modes
- **Manual (default):** buyer reviews each `VALIDATED` submission (sample + report) on `[id].vue` and accepts/rejects; allocation runs on accept.
- **Auto-accept (optional, behind a flag, default off):** validated submissions auto-accept via the same algorithm until target met.

### Under-fill & close
- Deadline with target unmet → `EXPIRED`. Nothing extra to pay; refund unspent escrow (Phase 5). (Per-unit makes under-fill a non-event.)
- Buyer may close early and refund the remainder.

### Steps
1. Implement the allocation function exactly as above (transactional, optimistic-locked on `version`).
2. Buyer review UI on `[id].vue`: list `VALIDATED` submissions with sample + report + accept/reject.
3. Wire accept → allocation → escrow release (Phase 5) → `PAID` + delivery unlock (Phase 6).
4. Request expiry: a scheduled check or lazy on-read → status + refund.
5. Update remaining-capacity displays to read post-allocation truth.

### Acceptance criteria (write as tests first)
- **Multi-provider partial fill:** target 10,000; A validated 4,000, B validated 7,000. Accept A then B → A:4,000, B:6,000 `PARTIALLY_ACCEPTED`, request `COMPLETED`, paid 10,000×price; B's surplus 1,000 not purchased.
- **Individual over-delivery:** target 5,000, one submission validated 8,000 → accept 5,000, `PARTIALLY_ACCEPTED`, pay 5,000.
- **Race:** two concurrent acceptances for the last 1,000 → exactly 1,000 total accepted; budget never exceeded.
- **Dedup:** B overlaps A by 500 (declared key) → B's accepted excludes 500; no double-pay.
- **Under-fill:** target 10,000, only 4,000 ever accepted, deadline passes → `EXPIRED`, refund = 6,000×price.

---

## Phase 5 — Escrow & payments (Stripe)

**Goal:** Funds held on request funding, released per accepted submission, refunded on close. The trust backbone — without held funds neither side commits. (`stripe` is already a dependency; test keys exist — but rotate per Phase 0.)

**Decision:** Stripe Connect (destination charges / transfers to providers' connected accounts). Semi-manual release is fine for MVP.

### Steps
1. **Provider onboarding:** Connect onboarding so providers can receive payouts; store the account id on the user (add a column). **Never collect raw bank/card details in-app** — use Stripe's hosted onboarding/checkout. (Entering financial credentials into app fields is prohibited; always hand off to Stripe's own UI.)
2. **Funding a request:** on `DRAFT → OPEN`, hold `budget` (or hold incrementally for pooled funding). Record a `hold` ledger entry.
3. **Release on acceptance:** transfer `amount_due` to the provider's connected account; record `release`. Release after any acceptance window (Phase 6).
4. **Refund on close:** on `COMPLETED` (rounding remainder), `EXPIRED`, or cancel → refund unspent to buyer; record `refund`.
5. **Idempotency & webhooks:** every money op idempotent (idempotency keys); reconcile via Stripe webhooks → ledger. Never mutate state on a client callback alone; trust the webhook.

### Acceptance criteria
- Funding holds exactly `budget`; ledger satisfies `held == released + refunded + still_held` always.
- Accepting transfers exactly `amount_due`; double-firing accept doesn't double-pay (idempotency test).
- Closing under-filled refunds exactly the remainder.
- No card/bank PII in the app DB.

> If real Stripe wiring is blocked, implement a **`FakePaymentProvider`** behind the same interface (records ledger entries, no real charges) so Phases 4/6 are buildable/testable. Swap to Stripe later without touching call sites.

---

## Phase 6 — Gated delivery (MinIO)

**Goal:** Buyer sees enough to decide (sample + report) but gets the full data only after payment clears — the practical answer to "can't judge data until you have it, won't pay once you do." MinIO is already in `docker-compose.yml`; `boto3` is already a dependency; `Submission` already has `storage_location`, `access_token_id`, `access_expiry`, `download_limit`, `owner_signature`.

**Decision:** MinIO/S3 with **time-limited pre-signed URLs**. DB stores keys + gate state, never public URLs.

### Steps
1. Store full files privately; only the sample is viewable pre-payment.
2. On `PAID`, issue a short-lived pre-signed URL for that submission's object (set `access_expiry`, decrement/track `download_limit`). Gate URL generation on submission state — never issue for non-`PAID` (or non-in-window) submissions.
3. **Acceptance window (recommended):** a short buyer-confirmation window between `ACCEPTED` and escrow `release`. Buyer downloads, confirms match → release. Auto-release on timeout so providers aren't stranded. If skipped for v1, document it.
4. Notifications on key transitions (submission received / validated / accepted / rejected / paid / request completed/expired) — email or in-app.

### Acceptance criteria
- Buyer can fetch any `VALIDATED` submission's sample, but a full-file URL only issues for `PAID` (or in-window `ACCEPTED`).
- Pre-signed URLs expire; expired/forged URLs fail.
- The MinIO bucket is private; direct access without a signed URL is denied.

---

## Phase 7 — Reputation & disputes (lightweight)

**Goal:** Cheap trust signals + a non-empty path when things go wrong. The `UserAnalytics` table already exists — wire into it.

### Steps
1. **Reputation:** after `PAID` (or refund), both sides leave a 1–5 rating + comment tied to the request (`reviews` table). Update `UserAnalytics.reputation_score`, `total_transactions`, `successful_transactions`, `provider_quality_score`. Show count + average on profiles and inline.
2. **Disputes:** within the acceptance window, buyer opens a dispute on a submission (`DISPUTED`), pausing that submission's escrow release. Resolution **manual** for MVP (admin queue/view) → `PAID` or refund. No automated adjudication.

### Acceptance criteria
- A dispute pauses release for exactly that submission, nothing else.
- Ratings only possible after a completed transaction.

---

## Phase 8 — EU / GDPR & licensing (cheap now, expensive later)

**Goal:** Bake in legal hygiene that's trivial at upload time and painful to retrofit. You're EU-based; do this in the MVP. (The frontend already has `pages/privacy.vue` and `pages/terms.vue` stubs to fill.)

### Steps
1. **Provider warranties at submission** (enforced checkboxes, stored with the submission, reuse `owner_signature`): right to sell/share; no unconsented personal data or properly anonymized.
2. **License on every request/dataset** (Phase 1 seed); the accepted license travels with delivered data and is shown to the buyer.
3. **Takedown mechanism:** flag/remove a dataset alleged to contain personal data / infringe; revoke outstanding pre-signed URLs (flip the gate, expire `access_expiry`).
4. **ToS / privacy content:** fill `terms.vue` / `privacy.vue` with placeholders documenting the platform's processor/controller role — mark for legal review; don't present as authoritative legal text.

### Acceptance criteria
- A submission can't complete without affirming warranties.
- Every delivered dataset carries a license record.
- A flagged dataset can be made unreachable (URLs revoked / gate flipped).

---

## Cross-cutting: testing strategy

There's no test suite yet — add one (pytest for backend). Prioritize:
- **State machines** (`DataRequest`, `Submission` transitions) and the **Phase 4 allocation** — highest bug density.
- **Money invariants as property tests:** for any sequence of accepts/refunds, `held == released + refunded + still_held` and `sum(accepted) ≤ amount_required`.
- **Concurrency test** for the allocation race (Phase 4) — most likely skipped, most likely to cost money.
- **One end-to-end happy path:** post → fund → two partial submissions → accept both (one capped) → pay → deliver → review.

---

## Recommended build order & dependencies

```
Phase 0  Orientation + hygiene + bug fixes   (blocks everything; rotate .env FIRST)
  └─► Phase 1  Alembic + model + lifecycles   (spine)
        ├─► Phase 2  Request spec + creation
        │     └─► Phase 3  Submission + ingest validation
        │           └─► Phase 4  Fulfilment engine  ◄── core MVP value
        ├─► Phase 5  Escrow & payments  (start in parallel after P1 via FakePaymentProvider)
        │     └─► (wires into Phase 4 acceptance)
        └─► Phase 6  Gated delivery (MinIO)  (after P3 storage + P4 acceptance)
Phase 7  Reputation & disputes               (after the core loop works end-to-end)
Phase 8  GDPR & licensing                    (warranties slot into P3; finish here)
```
Smallest thing that proves the business: **0 → 1 → 2 → 3 → 4 → 5 (fake then real) → 6.** Phases 7–8 harden it.

---

## Explicitly out of scope for the MVP (do NOT build)

Note as TODOs; don't implement.
- API / streaming access (files only).
- Automated quality scoring / ML validation beyond schema + count + key checks. (The `quality_score` column can stay 0 for now.)
- Subscriptions, recurring/tiered/dynamic pricing.
- In-platform data cleaning / transformation / enrichment.
- Crypto, tokens, on-chain anything.
- Cross-provider *fuzzy* dedup / entity resolution (only exact declared-key dedup is in scope).
- Automated dispute adjudication (manual only).
- Multi-currency, VAT/tax automation beyond what Stripe does out of the box (flag VAT for legal/finance).
- Advanced search/recommendations (basic filters only).
- Letting one account be both requester and provider (current role model forbids it — flag, don't build).

---

## Open product questions (flag, proceed with the stated default — don't block)

1. **Scarcer side?** Demand (requesters) or supply (providers)? Determines whether to polish the request-backer flow or provider onboarding first. *Default: optimize the request flow — the kickstarter mechanic uses demand to pull supply.*
2. **One account, both roles?** Current model says no (role on the account). *Default: keep single-role for MVP; revisit.*
3. **Coverage requests** (which records, not just how many) — v1 or fast-follow? *Default: quantity-only for v1, columns nullable.*
4. **Superset columns on delivery** — strip to spec, or hand over the full file? *Default: full file, noted.*
5. **Acceptance window** length + auto-release timeout. *Default: short window with auto-release; pick concrete days with product.*
6. **Exclusive vs non-exclusive** default license (exclusivity conflicts with multi-provider pooling). *Default: non-exclusive; flag the tension.*
