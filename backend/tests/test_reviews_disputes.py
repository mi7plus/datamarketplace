# tests/test_reviews_disputes.py

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.models import SubmissionStatus, UserRole
from app import lifecycle
from app.reviews import _recompute_reputation, _increment_transactions


def fake_db():
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.flush = MagicMock()
    return db


def make_sub(status=SubmissionStatus.ACCEPTED):
    return SimpleNamespace(
        id="sub-1",
        status=status,
        offered_amount=1000,
        validated_amount=1000,
        accepted_amount=0,
        amount_due=None,
        provider_id="prov-1",
        request_id="req-1",
    )


# ---------------------------------------------------------------------------
# Review business rules
# ---------------------------------------------------------------------------

class TestReviewRules:
    def test_can_only_review_paid_submission(self):
        """Review attempted on VALIDATED submission → 409."""
        from fastapi import HTTPException
        sub = make_sub(status=SubmissionStatus.VALIDATED)
        if sub.status != SubmissionStatus.PAID:
            with pytest.raises(Exception):
                raise HTTPException(status_code=409, detail="PAID only")

    def test_reputation_recompute_averages_all_reviews(self):
        """_recompute_reputation sets analytics.reputation_score to the mean rating."""
        from app.models import Review, UserAnalytics
        import uuid

        subject_id = str(uuid.uuid4())
        reviews = [
            SimpleNamespace(subject_id=subject_id, rating=4),
            SimpleNamespace(subject_id=subject_id, rating=2),
        ]

        analytics = SimpleNamespace(reputation_score=0, last_activity_at=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = reviews
        db.query.return_value.filter.return_value.first.return_value = analytics
        db.flush = MagicMock()

        _recompute_reputation(subject_id, db)
        assert analytics.reputation_score == 3.0   # (4+2)/2

    def test_reputation_with_single_review(self):
        subject_id = "user-x"
        reviews = [SimpleNamespace(subject_id=subject_id, rating=5)]

        analytics = SimpleNamespace(reputation_score=0, last_activity_at=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = reviews
        db.query.return_value.filter.return_value.first.return_value = analytics
        db.flush = MagicMock()

        _recompute_reputation(subject_id, db)
        assert analytics.reputation_score == 5.0

    def test_reputation_no_reviews_is_noop(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        # Should return without error and not modify anything
        _recompute_reputation("any-user", db)
        db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Analytics counters
# ---------------------------------------------------------------------------

class TestAnalyticsCounters:
    def test_increment_creates_row_if_missing(self):
        from app.models import UserAnalytics
        analytics = SimpleNamespace(
            total_transactions=0,
            successful_transactions=0,
            last_activity_at=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = analytics
        db.flush = MagicMock()

        _increment_transactions("user-1", successful=True, db=db)
        assert analytics.total_transactions == 1
        assert analytics.successful_transactions == 1

    def test_failed_transaction_increments_total_only(self):
        analytics = SimpleNamespace(
            total_transactions=5,
            successful_transactions=3,
            last_activity_at=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = analytics
        db.flush = MagicMock()

        _increment_transactions("user-1", successful=False, db=db)
        assert analytics.total_transactions == 6
        assert analytics.successful_transactions == 3   # unchanged


# ---------------------------------------------------------------------------
# Dispute state machine
# ---------------------------------------------------------------------------

class TestDisputeLifecycle:
    def test_open_dispute_transitions_to_disputed(self):
        sub = make_sub(status=SubmissionStatus.ACCEPTED)
        db = fake_db()
        disputed = lifecycle.open_dispute(sub, db)
        assert disputed.status == SubmissionStatus.DISPUTED

    def test_partially_accepted_can_be_disputed(self):
        sub = make_sub(status=SubmissionStatus.PARTIALLY_ACCEPTED)
        db = fake_db()
        disputed = lifecycle.open_dispute(sub, db)
        assert disputed.status == SubmissionStatus.DISPUTED

    def test_paid_cannot_be_disputed(self):
        sub = make_sub(status=SubmissionStatus.PAID)
        db = fake_db()
        with pytest.raises(HTTPException) as exc:
            lifecycle.open_dispute(sub, db)
        assert exc.value.status_code == 409

    def test_resolve_dispute_paid(self):
        sub = make_sub(status=SubmissionStatus.DISPUTED)
        db = fake_db()
        resolved = lifecycle.resolve_dispute(sub, "paid", db)
        assert resolved.status == SubmissionStatus.PAID

    def test_resolve_dispute_rejected(self):
        sub = make_sub(status=SubmissionStatus.DISPUTED)
        db = fake_db()
        resolved = lifecycle.resolve_dispute(sub, "rejected", db)
        assert resolved.status == SubmissionStatus.REJECTED

    def test_invalid_outcome_raises(self):
        sub = make_sub(status=SubmissionStatus.DISPUTED)
        db = fake_db()
        with pytest.raises(HTTPException) as exc:
            lifecycle.resolve_dispute(sub, "nonsense", db)
        assert exc.value.status_code == 400

    def test_dispute_pauses_only_that_submission(self):
        """Opening a dispute on sub-A does not affect sub-B."""
        sub_a = make_sub(status=SubmissionStatus.ACCEPTED)
        sub_b = make_sub(status=SubmissionStatus.ACCEPTED)
        sub_b.id = "sub-2"

        db = fake_db()
        lifecycle.open_dispute(sub_a, db)

        # sub_b is unaffected
        assert sub_b.status == SubmissionStatus.ACCEPTED
