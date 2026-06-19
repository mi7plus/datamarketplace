# Data Marketplace — Fix List v4: Release-Path Lock + End-to-End Test

**Audience:** Claude Code
**Repo:** `mi7plus/datamarketplace` (branch `main`)
**Context:** F7–F9 verified done. Two items here: **F10** (a real concurrency hole on the release path — the mirror of the F2 fix) and **E2E** (one integration test that runs the whole loop against real Postgres + LocalStorage, where interaction bugs like F10 actually surface).

Process unchanged: one fix = one commit = one push; verify from a fresh clone; run `pytest` after each. The E2E and F10 regression tests need a live Postgres (`conftest.py` already loads `backend/.env`).

---

## F10 — Lock the release path (mirror of F2)

**Problem:** `confirm`, `claim`, the lazy `/download` check, and `run_auto_release_sweep` all funnel into `_release_and_pay`, which **takes no lock and re-checks no state under one.** Two release triggers can fire on the same submission concurrently — most realistically the **sweep at the same moment the buyer hits `/confirm`**, or two overlapping sweep runs. Both read `ACCEPTED`, both pass the dispute check, both release.

- **Real Stripe:** transfer is idempotent (`release_{submission.id}`) so no double payment, but the ledger `external_ref` (= transfer id) is identical → second insert hits the unique constraint → `IntegrityError`/500.
- **FakePaymentProvider (dev/test):** release ref is `fake_release_{uuid4()}` — **random per call** — so two ledger entries with different refs slip past the unique constraint → **double release in the ledger**, and tests can't even reproduce the Stripe guard.

**Fix — two parts:**

### 10a. Single locked chokepoint in `_release_and_pay`

Re-load request then submission `FOR UPDATE` (same lock order as `accept`), re-assert state under the lock, no-op if already released:

```python
def _release_and_pay(submission_id: str, db: Session) -> Submission:
    """
    Release escrow for an ACCEPTED/PARTIALLY_ACCEPTED submission and mark PAID.
    Re-loads BOTH rows FOR UPDATE (request first, then submission — same order as
    accept()) and re-checks status under the lock, so concurrent triggers
    (confirm / claim / lazy-download / sweep) serialise and only the first releases.
    Idempotent: a second caller sees PAID and returns a no-op.
    """
    # lock order: request first
    submission_pre = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission_pre:
        raise HTTPException(404, "Submission not found")

    data_request = (
        db.execute(select(DataRequest)
                   .where(DataRequest.id == str(submission_pre.request_id))
                   .with_for_update())
        .scalars().first()
    )
    submission = (
        db.execute(select(Submission)
                   .where(Submission.id == submission_id)
                   .with_for_update())
        .scalars().first()
    )

    # Re-check UNDER the lock — the decisive check
    if submission.status == SubmissionStatus.PAID:
        return submission                      # already released — clean no-op
    if submission.status not in ACCEPTED_STATUSES:
        return submission
    if _has_open_dispute(submission.id, db):
        return submission                      # dispute opened in the meantime

    payment = get_payment_provider()
    payment.release_to_provider(submission, db)
    submission = mark_paid(submission, db)
    _increment_transactions(str(data_request.requester_id), successful=True, db=db)
    _increment_transactions(str(submission.provider_id), successful=True, db=db)

    if data_request.status == RequestStatus.COMPLETED:
        balance = ledger_balance(db, data_request.id)
        if balance["remaining"] > Decimal("0"):
            payment.refund_to_buyer(data_request, balance["remaining"], db)

    db.commit()
    return submission
```

Update the four callers to pass `submission_id` (they already have it) instead of pre-loaded objects, and to use the returned submission. `_auto_release_if_due` keeps its cheap pre-checks (status/window/dispute) as an optimisation but **must not be relied on for correctness** — the authoritative re-check now lives inside the lock.

### 10b. Make the fake release ref deterministic

In `payments.py::FakePaymentProvider.release_to_provider`, change the ref from random to `f"fake_release_{submission.id}"` (and `hold` → `f"fake_hold_{request.id}"`, `refund` → keyed by request + amount). Then the unique `Ledger.external_ref` constraint catches duplicates in dev/test exactly as it does for Stripe — so a double-release becomes a caught no-op instead of a silent double-count, and it's testable.

### 10c. Per-row isolation in the sweep (robustness)

Wrap each submission in `run_auto_release_sweep` in `try/except` so one failing release (e.g. a provider with no connected Stripe account in real mode) doesn't abort the whole batch; log failures and the released count.

```python
for sub in due:
    try:
        data_request = db.query(DataRequest).filter(DataRequest.id == str(sub.request_id)).first()
        if data_request and _auto_release_if_due(sub.id, db):
            released += 1
    except Exception:
        db.rollback()
        logger.exception("auto-release failed for submission %s", sub.id)
```

**Tests:**
1. **Idempotency (deterministic, must-have):** accept a submission, then call the release path **twice** on the same id → exactly one `release` ledger entry, status `PAID`, second call a clean no-op (no 500, no second entry). With 10b this also passes for the Fake provider.
2. **Concurrency (threaded, real Postgres):** two threads/sessions calling the release path on the same submission → exactly one `release` ledger row; the other thread no-ops.
3. **Dispute race:** dispute opened after the cheap pre-check but before the lock → release is blocked under the lock.

**Acceptance:** No submission can be released twice via any combination of confirm/claim/download/sweep; the loser of a race no-ops cleanly; the Fake provider's ledger guard is now exercised by tests.

---

## E2E — One integration test for the whole loop

**Goal:** A single test that drives the real routers end-to-end against live Postgres + `LocalStorage` + `FakePaymentProvider`, exercising spec → escrow hold → ingest/validation → capped allocation → cross-provider dedup → window/sweep release → ledger integrity → gated download → review *together*. This is where interaction bugs (like F10) live; the unit tests each pass in isolation.

Create `backend/tests/test_e2e_full_loop.py`. No MinIO/Stripe needed: `LocalStorage` and `FakePaymentProvider` are the defaults. Bind helper field names to the actual auth/request/spec schemas where noted.

**Scenario (target 10 rows @ $1.00, unique key = `id`):**

| Step | Action | Expected |
|---|---|---|
| 1 | Register requester R + providers P1, P2; log in | tokens issued |
| 2 | R `POST /requests/` with spec (`unique_key=["id"]`), `amount_required=10`, `budget=10.00`, `price_per_unit=1.00`, future deadline | request `DRAFT` |
| 3 | R `POST /requests/{id}/fund` | `OPEN`; ledger `held=10.00` |
| 4 | P1 `POST /submissions/` CSV ids 1–6, `offered_amount=6`, `warranted=true` | `VALIDATED`, `validated_amount=6` |
| 5 | R `POST /submissions/{p1}/accept` | `ACCEPTED`; `accepted_amount=6`; request `PARTIALLY_FULFILLED`; `accepted_total=6`; `accepted_keys`=6 |
| 6 | P2 `POST /submissions/` CSV ids 4–13 (3 overlap, 7 new), `offered_amount=10` | `VALIDATED`, `validated_amount=10` |
| 7 | R `POST /submissions/{p2}/accept` | **no 500**; `PARTIALLY_ACCEPTED`; `accepted_amount=4` (capped at remaining, overlap excluded); `amount_due=4.00`; request `COMPLETED`; `accepted_total=10`; `accepted_keys`=10 (ids 1–10, each once) |
| 8 | Pre-payment: P? `GET /submissions/{p1}/download` | 403 (not PAID); `GET /sample` works |
| 9 | Backdate both `accepted_at` past the window (direct DB update), then `run_auto_release_sweep(db)` | both `PAID`; ledger `released=10.00`, `remaining=0` |
| 10 | R `GET /submissions/{p1}/download` | 200 + presigned/local URL |
| 11 | R leaves a review for P1 | review persisted; `UserAnalytics` counters updated |
| 12 | Final ledger assertion | `held == released + refunded + remaining` exactly; `released=10.00`; `remaining=0`; no row over budget |

**Skeleton:**

```python
# backend/tests/test_e2e_full_loop.py
import io, csv
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Submission, SubmissionStatus, RequestStatus
from app.payments import ledger_balance
from app.submissions import run_auto_release_sweep

client = TestClient(app)

def _csv(ids):
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["id", "value"])
    for i in ids: w.writerow([i, f"v{i}"])
    return buf.getvalue().encode()

def _register_login(email, role):
    client.post("/auth/register", json={"email": email, "password": "pw123456", "role": role})
    r = client.post("/auth/login", json={"email": email, "password": "pw123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def test_full_loop_dedup_cap_and_sweep_release():
    R  = _register_login("r@test.io", "requester")
    P1 = _register_login("p1@test.io", "provider")
    P2 = _register_login("p2@test.io", "provider")

    # 2–3: create + fund   (bind spec shape to DataRequestCreateSchema)
    req = client.post("/requests/", headers=R, json={
        "title": "ids", "unit": "row", "amount_required": 10,
        "pricing_mode": "per_unit", "price_per_unit": 1.0, "budget": 10.0,
        "required_format": "csv",
        "spec": {"columns": [{"name": "id", "type": "int", "required": True},
                             {"name": "value", "type": "string", "required": True}],
                 "unique_key": ["id"]},
        "deadline": (datetime.utcnow() + timedelta(days=7)).isoformat(),
    }).json()
    rid = req["id"]
    client.post(f"/requests/{rid}/fund", headers=R)

    db = SessionLocal()
    assert ledger_balance(db, rid)["held"] == Decimal("10.00")

    # 4–5: P1 submits 1–6, accepted fully
    s1 = client.post("/submissions/", headers=P1,
        files={"file": ("a.csv", _csv(range(1, 7)), "text/csv")},
        data={"request_id": rid, "offered_amount": 6, "warranted": "true"}).json()
    a1 = client.post(f"/submissions/{s1['id']}/accept", headers=R)
    assert a1.status_code == 200
    assert a1.json()["submission"]["accepted_amount"] == 6

    # 6–7: P2 submits 4–13 (overlap 4,5,6) — capped to 4 new, NO 500
    s2 = client.post("/submissions/", headers=P2,
        files={"file": ("b.csv", _csv(range(4, 14)), "text/csv")},
        data={"request_id": rid, "offered_amount": 10, "warranted": "true"}).json()
    a2 = client.post(f"/submissions/{s2['id']}/accept", headers=R)
    assert a2.status_code == 200, a2.text          # regression guard for F7
    body = a2.json()
    assert body["submission"]["accepted_amount"] == 4
    assert body["submission"]["status"] == SubmissionStatus.PARTIALLY_ACCEPTED
    assert body["request_status"] == RequestStatus.COMPLETED

    # 8: gated download blocked pre-payment
    assert client.get(f"/submissions/{s1['id']}/download", headers=R).status_code == 403

    # 9: elapse window + sweep
    for sid in (s1["id"], s2["id"]):
        sub = db.query(Submission).filter(Submission.id == sid).first()
        sub.accepted_at = datetime.utcnow() - timedelta(hours=999)
    db.commit()
    released = run_auto_release_sweep(db)
    assert released == 2

    # 10–12: download now works; ledger balances exactly
    assert client.get(f"/submissions/{s1['id']}/download", headers=R).status_code == 200
    bal = ledger_balance(db, rid)
    assert bal["released"] == Decimal("10.00")
    assert bal["remaining"] == Decimal("0")
    assert bal["held"] == bal["released"] + bal["refunded"] + bal["remaining"]
    db.close()
```

**Notes for Claude Code:**
- Bind payloads to the real schemas (`RegisterSchema`, `DataRequestCreateSchema`, the spec sub-schema, the submission multipart fields) — adjust field names if they differ.
- If a `license_id` is required on create, seed a license in a fixture and pass it.
- Use a **dedicated test database** (separate `POSTGRES_DB`) and truncate between runs so the test is repeatable; add a fixture that creates/drops schema via Alembic or `Base.metadata`.
- Point `LocalStorage` at a tmp dir for the run.
- This test is the acceptance gate for the whole core loop — keep it green in CI.

---

## Order

```
F10a/b/c  release-path lock + deterministic fake ref + sweep isolation  ← real concurrency hole
E2E       full-loop integration test                                    ← the acceptance gate
```
Land F10 first (with its idempotency test), then add the E2E test — the E2E run is the thing that would have caught the release race in the first place.
