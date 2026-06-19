# Data Marketplace — Fix Punch-List v3

**Audience:** Claude Code (step-by-step execution)
**Repo:** `mi7plus/datamarketplace` (branch `main`)
**Context:** Fix list v2 (F1–F6) is verified done in a fresh clone — secrets purged, double-accept re-lock, acceptance window, Decimal money, ledger/webhook idempotency all landed. This list covers the three issues found reviewing that work. **F7 is a ship-blocker (it 500s on the exact case dedup exists for); F8 and F9 are correctness gaps, not blockers.**

---

## PROCESS — same discipline as v2

1. **One fix = one commit = one push**, descriptive message, push immediately. Don't batch.
2. **No history rewrites.**
3. **Verify from a fresh clone, not the working copy:**
   ```bash
   rm -rf /tmp/verify && git clone --depth 1 <repo-url> /tmp/verify
   ```
   then grep the fresh clone for the change.
4. Run `cd backend && pytest` after each fix. For F7 the new test MUST hit a real Postgres (the `uq_accepted_key` constraint is the whole point — a MagicMock can't reproduce the bug).

---

## F7 — Dedup persists the wrong keys (SHIP-BLOCKER)

**Problem:** In `backend/app/lifecycle.py::accept_submission`, after computing `accepted`, the code persists:
```python
for kh in submission.key_hashes[:accepted]:
    db.add(AcceptedKey(request_id=request.id, key_hash=kh))
```
`key_hashes[:accepted]` takes the **first** `accepted` hashes of the submission. On **partial overlap**, those first entries can be the already-accepted ones, so the insert violates the `uq_accepted_key` unique constraint → `IntegrityError` → the acceptance **500s**.

**Concrete failure:** A accepted records 0–29. B submits 20–69 (10 overlap, 40 new). `accepted` is correctly 40, but `key_hashes[:40]` = records 20–59, which includes 20–29 (already in `accepted_keys`). Duplicate insert → 500. Even without the constraint it would persist the wrong set (20–59) and miss 60–69, corrupting future dedup counts.

**Fix:** Credit and persist the **non-overlapping** keys, capped at remaining — derive `accepted` from that set so the count and the persisted rows always agree:
```python
remaining = (request.amount_required or 0) - (request.accepted_total or 0)

if getattr(submission, "key_hashes", None):
    already_accepted = {
        row.key_hash
        for row in db.query(AcceptedKey)
        .filter(AcceptedKey.request_id == str(request.id))
        .all()
    }
    # keep submission order; drop anything already accepted for this request
    new_hashes = [h for h in submission.key_hashes if h not in already_accepted]
    creditable = new_hashes[:remaining]          # cap at remaining capacity
    accepted = len(creditable)
else:
    creditable = None
    accepted = min(submission.validated_amount, remaining)

# ... status / amount_due / accepted_total math using `accepted` ...

if creditable:
    for kh in creditable:
        db.add(AcceptedKey(request_id=request.id, key_hash=kh))
```
Notes:
- Derive `accepted` from `len(creditable)` when a key is declared — don't keep a separate `eligible = validated_amount - overlap` path that can disagree with the slice.
- If `validated_amount` can differ from `len(key_hashes)` (e.g. out-of-coverage rows excluded at ingest), prefer the key-list length as the source of truth when keys exist.
- Keep this inside the existing single locked commit (don't add a separate commit).

**Tests (must use a real Postgres — reuse the `test_allocation_race.py` DB harness):**
1. **Partial overlap:** A accepts 0–29; B submits 20–69 → B becomes `PARTIALLY_ACCEPTED` with `accepted_amount == 40`; `accepted_keys` for the request == 70 rows (0–69, no dupes); B paid for 40; **no 500**.
2. **No overlap:** unchanged behaviour (full credit).
3. **Full overlap:** B → `REJECTED`, `accepted_amount == 0`, no new keys, no 500.

Also fix the existing `tests/test_cross_provider_dedup.py`: the partial-overlap cases currently re-implement the arithmetic inline instead of calling `accept_submission`, and the mock DB can't raise the unique-constraint error — so they pass while the bug is live. Replace them with the real-DB tests above (keep the pure-arithmetic ones only as fast smoke checks if you like).

**Acceptance:** Partial-overlap acceptance succeeds (no 500), pays only for genuinely new records, and `accepted_keys` contains each record exactly once.

---

## F8 — Providers can be stranded: auto-release is buyer-only and lazy

**Problem:** The acceptance-window auto-release only fires inside the `download` endpoint, which is gated by `_require_request_owner` — i.e. **only the buyer** can trigger it. A buyer who accepts and then disappears never calls `download` or `confirm`, so the provider is never paid. There is no scheduled sweep and no provider-reachable trigger, despite the `confirm()` docstring claiming providers are never stranded.

**Fix (pick one; a sweep is preferred):**

*Option A — background sweep (preferred):* a periodic task that releases `ACCEPTED`/`PARTIALLY_ACCEPTED` submissions whose `accepted_at + ACCEPTANCE_WINDOW_HOURS` has passed and that have no open dispute. Run it via APScheduler in-process, or a management command invoked by cron/a worker. It calls the same `_release_and_pay(...)` path (which is idempotent via `release_{submission.id}` + the unique ledger ref).

*Option B — provider-reachable claim endpoint:* `POST /submissions/{id}/claim` callable by the **provider**, which performs the same window-elapsed + no-open-dispute check and releases. (Still add A eventually; B alone depends on the provider remembering to poll.)

Either way: fix the `confirm()` docstring to match reality, and make sure the lazy check in `download` and the new path share one helper so the rules can't drift.

**Acceptance:** A submission accepted, window elapsed, buyer never returns, no dispute → provider is paid (sweep) or can self-release (claim), without any buyer action. An open dispute still blocks it.

---

## F9 — `accepted_at` written outside the lock (can break auto-release)

**Problem:** In `submissions.py::accept`, `accepted_at` is set in a **second** commit *after* `accept_submission` has committed and released the row locks. If the process dies between the two commits, the submission is `ACCEPTED` with `accepted_at = NULL`. The auto-release check requires `accepted_at` to be set, so such a submission can **never** auto-release — a permanent stuck state.

**Fix:** Set `accepted_at` **inside** `accept_submission`, before its single commit, so the status change and the window anchor are atomic:
```python
# in accept_submission, when new_status is ACCEPTED or PARTIALLY_ACCEPTED:
submission.accepted_at = datetime.utcnow()
```
Remove the separate `accepted_at` assignment + second `db.commit()` from the `accept` endpoint.

**Acceptance:** Every `ACCEPTED`/`PARTIALLY_ACCEPTED` submission has a non-null `accepted_at` set in the same transaction as the status change; no second post-lock commit for it.

---

## Backlog (note, don't build now)

- **Dedup query scales O(accepted-so-far) per accept** — it loads every accepted key for the request into a Python set on each acceptance. Fine at MVP volume with `idx_accepted_keys_request`, but at scale push the membership test into SQL (`key_hash IN (...)` or a join / `NOT EXISTS`) instead of materialising the set in Python.

---

## Order

```
F7  dedup key persistence + real-DB test   ← ship-blocker (500s on partial overlap)
F8  provider auto-release (sweep)           ← correctness (no stranded providers)
F9  accepted_at inside the lock             ← correctness (no stuck ACCEPTED rows)
```
Commit + push each separately; verify F7 from a fresh clone with the real-Postgres partial-overlap test green before calling dedup done.
