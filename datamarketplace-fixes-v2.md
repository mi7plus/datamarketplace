# Data Marketplace — Fix Punch-List v2

**Audience:** Claude Code (step-by-step execution)
**Repo:** `mi7plus/datamarketplace` (branch `main`, currently at a single squashed commit)
**Why v2:** The v1 fixes (F2–F6) are **not present** on `main` — the accept/allocation code is unchanged and a new `frontend/.env` secret was committed. Likely cause: a history rewrite (to scrub the old `.env`) reset the tree to a pre-fix snapshot, or the edits were never committed/pushed. **Do F0 before redoing anything.**

---

## PROCESS — read first, follow for every fix

This is the part that failed last time. Enforce it:

1. **One fix = one commit = one push.** After each F-item below, make a single focused commit with a real message (not "commit") and `git push` immediately. Never batch multiple fixes into one commit.
2. **Never squash or rewrite history to "clean up" again** until all fixes are pushed. The only history rewrite permitted is the secret scrub in F1, and that comes **after** F0 confirms nothing else is lost.
3. **Verify from a fresh clone, not the working copy.** After pushing a fix, run:
   ```bash
   rm -rf /tmp/verify && git clone --depth 1 <repo-url> /tmp/verify
   ```
   and grep the fresh clone for the change. A working copy can show edits that were never pushed; a fresh clone shows only what's on `main`.
4. After each fix, run the test suite (`cd backend && pytest`) before moving on.

---

## F0 — Recover the lost work BEFORE redoing it

The v1 fixes may still exist in git's reflog or as uncommitted changes. Check before spending effort re-implementing.

```bash
git status                 # uncommitted fixes sitting in the working tree?
git stash list             # stashed?
git reflog --date=iso | head -50   # commits dropped by the squash/rewrite?
git log --oneline --all --reflog | head -50
```

- If `accept_submission` with dedup, or an acceptance-window `confirm` endpoint, appears in any reflog commit → recover it: `git cherry-pick <sha>` (or `git checkout <sha> -- backend/app/...`), then commit + push.
- If the work is genuinely gone → proceed to F1+ and re-implement, committing per the PROCESS rules.

**Report** which items (if any) were recovered vs need redoing, before continuing.

---

## F1 — Purge the new committed secret

**Problem:** `frontend/.env` is tracked and contains `API_SECRET=supersecret...`. The `*.env` line in `.gitignore` does NOT help — gitignore is ignored for already-tracked files. (Root and `backend/.env` were already scrubbed — good; don't undo that.)

**Steps:**
1. **Rotate** whatever `API_SECRET` is — treat it as compromised (human action, in the relevant dashboard/service).
2. `git rm --cached frontend/.env` and commit.
3. Add `frontend/.env.example` with empty placeholders.
4. Scrub from history: `git filter-repo --path frontend/.env --invert-paths` (or BFG), then **pause for human confirmation**, then force-push.
5. Verify: `git ls-files | grep -E '(^|/)\.env$'` is empty, and `git log --all --full-history -- frontend/.env` returns nothing.

**Acceptance:** No `.env` tracked anywhere; `API_SECRET` rotated; app still runs from a local untracked `frontend/.env`.

---

## F2 — Fix double-accept of the same submission + add a real-DB race test

**Problem:** In `backend/app/submissions.py::accept`, `submission.status != VALIDATED` is checked **before** the `data_requests` row lock, and `lifecycle.accept_submission` never re-checks the submission under the lock. Two concurrent accepts of the *same* submission both pass the check, the request lock serializes them but doesn't protect the submission, so the second one allocates again and fires a second `release_to_provider` → provider paid twice.

**Steps:**
1. After acquiring the request lock, **re-load the submission WITH a row lock and re-assert state**, inside the critical section:
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
   Lock order everywhere: request first, then submission (avoid deadlocks).
2. Keep the capped allocation; it's correct once the re-check is in place.
3. **Add `backend/tests/test_allocation_race.py` hitting a real Postgres** (testcontainers or a dedicated test DB), with two threads/sessions:
   - both accepting the **same** submission → exactly one succeeds; provider paid once; `accepted_total` incremented once; ledger has exactly one `release`.
   - two **different** submissions racing for the last slot → total accepted == `amount_required`; budget never exceeded; loser reduced/`REJECTED`.

   This closes the "race tests left as a TODO" note in `test_allocation.py`.

**Acceptance:** Both race tests pass against a real DB; same submission can never be accepted twice.

---

## F3 — Implement cross-provider deduplication

**Problem:** `lifecycle.accept_submission` sets `eligible = submission.validated_amount` with no overlap subtraction. Provider B can resubmit Provider A's rows and be paid for them.

**Steps:**
1. When the request `spec` declares a unique key, compute per-record key hashes at ingest (`ingest.py`, alongside `dataset_hash`) and store them for the submission.
2. Persist a per-request accepted key-set (new table `accepted_keys(request_id, key_hash)` with a unique constraint on the pair).
3. In `accept_submission`, before capping:
   `eligible = validated_amount − |submission_keys ∩ already_accepted_keys(request)|`, then `accepted = min(eligible, remaining)`. On acceptance, insert the newly-accepted keys **inside the same locked transaction** as F2.
4. No declared key → skip dedup, keep the buyer-beware note; don't block.

**Acceptance:** Test where B overlaps A by N rows (declared key) → B's `accepted_amount` excludes N; no double-pay; each record counted once in `accepted_total`.

---

## F4 — Add an acceptance window (revives disputes + protects the buyer)

**Problem:** `accept()` runs allocation → release → `mark_paid` in one request, so submissions hit terminal `PAID` instantly. The buyer pays on the **sample** and only downloads the full file **after** payment, with no recourse; `disputes.py::open` requires `ACCEPTED`/`PARTIALLY_ACCEPTED`, which now never persist → dispute flow is dead code.

**Steps:**
1. Split acceptance from release. `/accept`: allocation → `ACCEPTED`/`PARTIALLY_ACCEPTED`, **escrow stays held**, set `accepted_at`. Do **not** release here.
2. Add `POST /submissions/{id}/confirm` (buyer): after downloading and verifying the full file → `release_to_provider` + `mark_paid`.
3. Allow full-file download for `ACCEPTED` submissions (not only `PAID`) so the buyer can verify before release.
4. Auto-release: submissions `ACCEPTED` longer than `ACCEPTANCE_WINDOW_HOURS` (env, default 72) auto-confirm via a lazy on-read check plus an optional sweep, so providers aren't stranded. A dispute opened in the window pauses auto-release (already wired in `disputes.py`).

**Acceptance:** A submission stays `ACCEPTED` until confirm/timeout; a dispute can be opened during the window and pauses release; auto-release fires after the window; buyer can download the full file before funds release.

---

## F5 — Move money off `Float`

**Problem:** `DataRequest.budget`, `price_per_unit`, `Submission.amount_due`, `Ledger.amount` are `Float`. The scattered `round(..., 2)` and the `remaining > 0.01` fuzzy compare are drift symptoms.

**Steps:**
1. Alembic migration: those columns → `Numeric(12, 2)` (or store integer minor units/cents).
2. Use `decimal.Decimal` in `payments.py` and `lifecycle.py`; replace the `> 0.01` fuzz with exact comparison.
3. Update `ledger_balance` and `amount_due` math to Decimal.

**Acceptance:** Property test — for any sequence of holds/releases/refunds, `held == released + refunded + still_held` **exactly** (no epsilon).

---

## F6 — Atomicity & idempotency hardening

**Problem cluster:**
- `accept_submission` commits twice (in `transition_submission`, then `_recalculate_request_status`); the request lock releases at the first commit, so a crash between them leaves an accepted submission on a not-yet-advanced request.
- release → `mark_paid` isn't atomic; the Stripe transfer is idempotent (`release_{submission.id}`) but `append_ledger` is not, so a retry double-records; no retry path for stuck `ACCEPTED`-but-unreleased rows.
- `webhooks.py` doesn't dedup on Stripe `event.id` (Stripe redelivers events).

**Steps:**
1. Fold allocation + both status updates into a **single commit** under the lock (one `db.commit()` at the end). Provide non-self-committing variants of the lifecycle helpers for use inside the transaction.
2. Make ledger writes idempotent: unique constraint on `external_ref` (or check-before-insert).
3. Add a reconciliation sweep: `ACCEPTED` rows with a successful transfer but no `PAID` → mark `PAID`; failed transfers → retry.
4. Persist processed Stripe `event.id`s and skip repeats in the webhook handler.

**Acceptance:** Replaying a webhook event is a no-op; a forced failure between release and `mark_paid` doesn't double-pay or double-record on retry; allocation is one atomic commit under the lock.

---

## Order & commit discipline

```
F0  recover lost work     ← do first; don't redo what reflog still has
F1  frontend/.env secret  ← then scrub (the only allowed history rewrite)
F2  double-accept + race test   ← ship-blocker (money)
F4  acceptance window           ← ship-blocker (buyer protection + disputes)
F3  dedup                       ← correctness (per-unit fairness)
F5  Decimal money               ← correctness (ledger integrity)
F6  atomicity / idempotency     ← hardening
```

Commit and push after **each** item with a descriptive message. After F2–F5, verify from a fresh clone and run the full suite (incl. the new race and dedup tests) against a real Postgres before calling the core loop production-ready.
