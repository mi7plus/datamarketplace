# tests/test_lifecycle.py
#
# Tests for the DataRequest and Submission state machines and invariant guards.
# Uses unittest.mock to avoid a real DB — the state machine logic is pure
# enough to test with simple stub objects.

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from types import SimpleNamespace

from app.models import RequestStatus, SubmissionStatus
from app import lifecycle


# ---------------------------------------------------------------------------
# Helpers — plain SimpleNamespace stubs (avoids SQLAlchemy instrumentation)
# ---------------------------------------------------------------------------

def make_request(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        status=kwargs.get("status", RequestStatus.OPEN),
        amount_required=kwargs.get("amount_required", 10_000),
        accepted_total=kwargs.get("accepted_total", 0),
        budget=kwargs.get("budget", 1_000.0),
        price_per_unit=kwargs.get("price_per_unit", 0.1),
        version=1,
    )


def make_submission(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        status=kwargs.get("status", SubmissionStatus.VALIDATED),
        offered_amount=kwargs.get("offered_amount", 5_000),
        validated_amount=kwargs.get("validated_amount", 5_000),
        accepted_amount=kwargs.get("accepted_amount", 0),
        amount_due=None,
    )


def fake_db():
    """A mock Session that no-ops commit/refresh."""
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


# ---------------------------------------------------------------------------
# DataRequest state machine
# ---------------------------------------------------------------------------

class TestRequestTransitions:
    def test_draft_to_open(self):
        r = make_request(status=RequestStatus.DRAFT)
        db = fake_db()
        result = lifecycle.open_request(r, db)
        assert result.status == RequestStatus.OPEN

    def test_open_to_expired(self):
        r = make_request(status=RequestStatus.OPEN)
        db = fake_db()
        result = lifecycle.expire_request(r, db)
        assert result.status == RequestStatus.EXPIRED

    def test_completed_is_terminal(self):
        r = make_request(status=RequestStatus.COMPLETED)
        db = fake_db()
        with pytest.raises(HTTPException) as exc:
            lifecycle.transition_request(r, RequestStatus.OPEN, db)
        assert exc.value.status_code == 409

    def test_expired_is_terminal(self):
        r = make_request(status=RequestStatus.EXPIRED)
        db = fake_db()
        with pytest.raises(HTTPException):
            lifecycle.transition_request(r, RequestStatus.OPEN, db)

    def test_invalid_transition_raises(self):
        r = make_request(status=RequestStatus.DRAFT)
        db = fake_db()
        with pytest.raises(HTTPException) as exc:
            lifecycle.transition_request(r, RequestStatus.COMPLETED, db)
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Submission state machine
# ---------------------------------------------------------------------------

class TestSubmissionTransitions:
    def test_pending_to_validated(self):
        s = make_submission(status=SubmissionStatus.PENDING, validated_amount=None)
        db = fake_db()
        result = lifecycle.validate_submission(s, 4_000, {"rows": 4_000}, db)
        assert result.status == SubmissionStatus.VALIDATED
        assert result.validated_amount == 4_000

    def test_pending_zero_rows_to_rejected_invalid(self):
        s = make_submission(status=SubmissionStatus.PENDING, validated_amount=None)
        db = fake_db()
        result = lifecycle.validate_submission(s, 0, {"error": "no conforming rows"}, db)
        assert result.status == SubmissionStatus.REJECTED_INVALID

    def test_paid_is_terminal(self):
        s = make_submission(status=SubmissionStatus.PAID)
        db = fake_db()
        with pytest.raises(HTTPException):
            lifecycle.transition_submission(s, SubmissionStatus.ACCEPTED, db)

    def test_invalid_transition_raises(self):
        s = make_submission(status=SubmissionStatus.PENDING)
        db = fake_db()
        with pytest.raises(HTTPException):
            lifecycle.transition_submission(s, SubmissionStatus.PAID, db)


# ---------------------------------------------------------------------------
# Acceptance / allocation logic
# ---------------------------------------------------------------------------

class TestAcceptanceAllocation:
    def test_full_acceptance(self):
        r = make_request(amount_required=5_000, accepted_total=0, price_per_unit=0.1)
        s = make_submission(offered_amount=5_000, validated_amount=5_000)
        db = fake_db()
        sub, req = lifecycle.accept_submission(s, r, db)
        assert sub.accepted_amount == 5_000
        assert sub.status == SubmissionStatus.ACCEPTED
        assert sub.amount_due == pytest.approx(500.0)
        assert req.status == RequestStatus.COMPLETED

    def test_over_delivery_capped(self):
        """Provider validates 8,000 but only 5,000 needed → PARTIALLY_ACCEPTED."""
        r = make_request(amount_required=5_000, accepted_total=0, price_per_unit=0.1)
        s = make_submission(offered_amount=8_000, validated_amount=8_000)
        db = fake_db()
        sub, req = lifecycle.accept_submission(s, r, db)
        assert sub.accepted_amount == 5_000
        assert sub.status == SubmissionStatus.PARTIALLY_ACCEPTED
        assert req.accepted_total == 5_000
        assert req.status == RequestStatus.COMPLETED

    def test_multi_provider_partial_fill(self):
        """A fills 4,000 of 10,000 then B fills remaining 6,000 (capped from 7,000)."""
        r = make_request(amount_required=10_000, accepted_total=0, price_per_unit=0.1)
        db = fake_db()

        a = make_submission(offered_amount=4_000, validated_amount=4_000)
        a, r = lifecycle.accept_submission(a, r, db)
        assert a.accepted_amount == 4_000
        assert r.accepted_total == 4_000
        assert r.status == RequestStatus.PARTIALLY_FULFILLED

        b = make_submission(offered_amount=7_000, validated_amount=7_000)
        b, r = lifecycle.accept_submission(b, r, db)
        assert b.accepted_amount == 6_000          # capped at remaining
        assert b.status == SubmissionStatus.PARTIALLY_ACCEPTED
        assert r.accepted_total == 10_000
        assert r.status == RequestStatus.COMPLETED

    def test_zero_remaining_rejects(self):
        """Target already met — any further submission gets REJECTED."""
        r = make_request(amount_required=5_000, accepted_total=5_000)
        s = make_submission(offered_amount=3_000, validated_amount=3_000)
        db = fake_db()
        sub, req = lifecycle.accept_submission(s, r, db)
        assert sub.accepted_amount == 0
        assert sub.status == SubmissionStatus.REJECTED

    def test_unvalidated_submission_raises(self):
        r = make_request()
        s = make_submission(status=SubmissionStatus.PENDING, validated_amount=None)
        db = fake_db()
        with pytest.raises(HTTPException) as exc:
            lifecycle.accept_submission(s, r, db)
        assert exc.value.status_code == 409

    def test_open_request_becomes_partially_fulfilled(self):
        r = make_request(amount_required=10_000, accepted_total=0, status=RequestStatus.OPEN)
        s = make_submission(offered_amount=3_000, validated_amount=3_000)
        db = fake_db()
        _, req = lifecycle.accept_submission(s, r, db)
        assert req.status == RequestStatus.PARTIALLY_FULFILLED


# ---------------------------------------------------------------------------
# Dispute flow
# ---------------------------------------------------------------------------

class TestDisputeFlow:
    def test_accepted_to_disputed_to_paid(self):
        s = make_submission(status=SubmissionStatus.ACCEPTED)
        db = fake_db()
        s = lifecycle.open_dispute(s, db)
        assert s.status == SubmissionStatus.DISPUTED
        s = lifecycle.resolve_dispute(s, "paid", db)
        assert s.status == SubmissionStatus.PAID

    def test_accepted_to_disputed_to_rejected(self):
        s = make_submission(status=SubmissionStatus.ACCEPTED)
        db = fake_db()
        s = lifecycle.open_dispute(s, db)
        s = lifecycle.resolve_dispute(s, "rejected", db)
        assert s.status == SubmissionStatus.REJECTED

    def test_invalid_dispute_outcome_raises(self):
        s = make_submission(status=SubmissionStatus.DISPUTED)
        db = fake_db()
        with pytest.raises(HTTPException):
            lifecycle.resolve_dispute(s, "ambiguous", db)
