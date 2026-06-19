# Data Marketplace — Post-Build Fix Punch-List

**Audience:** Claude Code (step-by-step execution)
**Repo:** `mi7plus/datamarketplace`
**Context:** Phases 0–8 of the implementation plan are built. This list addresses correctness, security, and design gaps found in review. Work top-to-bottom; **F1, F2, and F4 are ship-blockers — do not deploy with real money/data until they're done.**

Rules: one fix = one small commit that leaves the app runnable. Every model change ships an Alembic migration. Add a test for each correctness fix. Don't refactor unrelated code.

---

## F1 — Purge committed secrets (URGENT, do first)

**Problem:** `.env` and `backend/.env` are still tracked by git and contain Stripe keys. The repo is public, so the keys are in history. Adding them to `.gitignore` did **not** untrack them.

**Steps:**
1. **Rotate the Stripe keys** in the Stripe dashboard — treat the committed ones as compromised. (A human must do this in Stripe; do not attempt it from code.)
2. Untrack the files: `git rm --cached .env backend/.env` then commit.
3. Scrub history: `git filter-repo --path .env --path backend/.env --invert-paths` (or BFG Repo-Cleaner), then force-push. **Pause and have a human confirm before force-pushing.**
4. Verify `git log --all --full-history -- .env backend/.env` returns nothing and `git ls-files | grep -E '(^|/)\.env$'` is empty.
5. Confirm `.gitignore` already covers `.env`, `backend/.env`, `*.env` (it does) and that `.env.example` carries only empty placeholders.

**Acceptance:** No `.env` in tree or history; keys rotated; app still starts from a local untracked `.env`.

---

## F2 — Fix double-accept of the same submission (double-pay) + add the real race test

**Problem:** In `backend/app/submissions.py::accept`, `submission.status != VALIDATED` is checked **before** the request-row lock is acquired, and `lifecycle.accept_submission` never re-checks the submission under the lock. Two concurrent accepts of the *same* submission both see `VALIDATED`; the `FOR UPDATE` lock on `data_requests` serializes them but doesn't protect the submission, so the second allocates again, increments `accepted_total` again, and fires a second `release_to_provider` → provider paid twice.

**Steps:**
1. In `accept`, after acquiring the request lock, **re-load the submission with a row lock and re-assert state inside the critical section:**
   ```python
   submission = (
       db.execute(
           select(Submission)
           .where(Submission.id == submission_id)
           .with_for_update()
       ).scalars().first()
   )
   if not submission or submission.status != SubmissionStatus.VALIDATED:
       raise HTTPException(409, "Submission is no longer available for acceptance")
   ```
   Acquire locks in a consistent order (request, then submission) everywhere to avoid deadlocks.
2. Keep the existing capped-allocation logic; it's correct once the re-check is in place.
3. **Add a real concurrency test** (`tests/test_allocation_race.py`) against a real Postgres (testcontainers or a dedicated test DB), running two sessions/threads:
   - (a) both accepting the **same** submission → exactly one succeeds, provider paid once, `accepted_total` incremented once.
   - (b) two **different** submissions racing for the last remaining slot → total accepted == `amount_required`, budget never exceeded, the loser is reduced/`REJECTED`.

   The existing `tests/test_allocation.py` uses `SimpleNamespace` + `MagicMock` and explicitly defers DB race tests — this fix closes that TODO.

**Acceptance:** Both race tests pass; the same submission can never be accepted twice; ledger shows exactly one `release` per accepted submission.

---

## F3 — Implement cross-provider deduplication

**Problem:** `lifecycle.accept_submission` sets `eligible = submission.validated_amount` with no overlap subtraction. Provider B can resubmit Provider A's exact rows and be paid for them, breaking the per-unit fairness the model depends on.

**Steps:**
1. When the request `spec` declares a unique key, persist the **accepted key-set per request** (a new table, e.g. `accepted_keys(request_id, key_hash)`, or reuse per-record hashes derived at ingest in `ingest.py`).
2. At ingest (`validate_dataset`), compute per-record key hashes for the declared key and store them on the submission (alongside `dataset_hash`).
3. In `accept_submission`, before capping: `eligible = validated_amount − |submission_keys ∩ already_accepted_keys|`. Then `accepted = min(eligible, remaining)`. On acceptance, add the newly-accepted keys to the request's accepted key-set (inside the same locked transaction as F2/F5).
4. If no key is declared, skip dedup and surface the existing buyer-beware note (don't block).

**Acceptance:** A test where B overlaps A by N rows (declared key) → B's `accepted_amount` excludes the N; neither is paid for the overlap; `accepted_total` counts each record once.

---

## F4 — Add an acceptance window (makes disputes reachable + protects the buyer)

**Problem:** `accept()` runs allocation → `release_to_provider` → `mark_paid` in one request, so submissions reach terminal `PAID` in milliseconds. The buyer pays on the **sample** and only downloads the full file **after** payment, with no recourse. `disputes.py::open` requires `ACCEPTED`/`PARTIALLY_ACCEPTED`, which now never persist — so the dispute flow is dead code.

**Steps:**
1. Split acceptance from release. On `/accept`: run allocation → status `ACCEPTED`/`PARTIALLY_ACCEPTED`, **escrow stays held** (no release yet). Record an `accepted_at` timestamp.
2. Add `/submissions/{id}/confirm` (buyer): buyer downloads the full file during the window, confirms it matches → `release_to_provider` + `mark_paid`.
3. Add auto-release: a submission `ACCEPTED` for longer than `ACCEPTANCE_WINDOW_HOURS` (env, e.g. 72) auto-confirms (lazy check on read + an optional scheduled sweep), so providers aren't stranded.
4. Allow full-file download during the window for `ACCEPTED` submissions (not only `PAID`), so the buyer can actually verify before release. Disputes opened during the window pause auto-release (already wired in `disputes.py`).

**Acceptance:** A submission sits in `ACCEPTED` until confirm/timeout; a dispute can be opened in that window and pauses release; auto-release fires after the window; the buyer can download the full file before funds release.

---

## F5 — Move money off `Float` to `Numeric`/integer minor units

**Problem:** `DataRequest.budget`, `price_per_unit`, `Submission.amount_due`, and `Ledger.amount` are `Float`. The scattered `round(..., 2)` and the `remaining > 0.01` fuzzy compare in the refund path are symptoms of drift that surfaces as ledger imbalances.

**Steps:**
1. Migrate the money columns to `Numeric(12, 2)` (or store integer cents). Alembic migration with explicit type casts.
2. Use `decimal.Decimal` in `payments.py` / `lifecycle.py`; drop the `> 0.01` fuzz in favor of exact comparisons.
3. Update `ledger_balance` and `amount_due` math to Decimal.

**Acceptance:** A property test — for any sequence of holds/releases/refunds, `held == released + refunded + still_held` **exactly** (no epsilon).

---

## F6 — Atomicity & idempotency hardening (polish)

**Problem cluster:**
- `accept_submission` commits twice (in `transition_submission`, then `_recalculate_request_status`); the request lock releases at the first commit, so a crash between them leaves an accepted submission on a not-yet-advanced request.
- `release_to_provider` → `mark_paid` isn't atomic. The Stripe transfer is idempotent (`release_{submission.id}`), but `append_ledger` is not — a retry double-records in the ledger. No retry path for stuck `ACCEPTED`-but-unreleased rows.
- `webhooks.py` calls `construct_event` but doesn't dedup on `event.id`; Stripe redelivers events.

**Steps:**
1. Fold allocation + both status updates into a **single commit** inside the locked critical section (one `db.commit()` at the end, not per-transition). Provide a transaction-scoped variant of the lifecycle helpers that don't self-commit.
2. Make ledger writes idempotent (unique constraint on `external_ref`, or check-before-insert) so retries can't double-record.
3. Add a small reconciliation path/sweep: submissions in `ACCEPTED` with a successful transfer but no `PAID` get marked `PAID`; transfers that failed get retried.
4. Persist processed Stripe `event.id`s and skip repeats in the webhook handler.

**Acceptance:** Replaying the same webhook event is a no-op; a forced failure between release and `mark_paid` doesn't double-pay or double-record on retry; allocation is a single atomic commit under the lock.

---

## Suggested order

```
F1  secrets        ← do first, blocks deploy
F2  double-accept  ← ship-blocker (money)
F4  accept window  ← ship-blocker (buyer protection + revives disputes)
F3  dedup          ← correctness (per-unit fairness)
F5  Decimal money  ← correctness (ledger integrity)
F6  atomicity/idempotency ← hardening
```

Each fix lands with its test. After F2–F5, run the full suite plus the new race and dedup tests against a real Postgres before considering the core loop production-ready.
