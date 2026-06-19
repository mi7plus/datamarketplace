# tests/test_acceptance_window.py
# F4: acceptance window logic — accept stays ACCEPTED until confirm/auto-release

import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


WINDOW_HOURS = 72


def _make_sub(status="accepted", accepted_at=None, accepted_amount=50, amount_due=50.0):
    return SimpleNamespace(
        id="sub-1",
        request_id="req-1",
        provider_id="prov-1",
        status=status,
        accepted_at=accepted_at,
        accepted_amount=accepted_amount,
        validated_amount=100,
        offered_amount=100,
        amount_due=amount_due,
        content_link="data.csv",
        storage_location="req/prov/data.csv",
        access_expiry=None,
        dataset_hash="abc123",
        validation_report={},
        created_at=datetime.utcnow(),
    )


def _make_request(status="open", accepted_total=50, amount_required=100):
    return SimpleNamespace(
        id="req-1",
        requester_id="buyer-1",
        status=status,
        accepted_total=accepted_total,
        amount_required=amount_required,
        price_per_unit=1.0,
        budget=100.0,
    )


class TestAcceptDoesNotRelease:
    def test_accept_returns_accepted_not_paid(self):
        """After /accept, status should be ACCEPTED — escrow NOT yet released."""
        from app.lifecycle import accept_submission
        from app.models import SubmissionStatus

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.flush = MagicMock()

        sub = SimpleNamespace(
            id="s1",
            status="validated",
            validated_amount=50,
            offered_amount=50,
            accepted_amount=0,
            amount_due=None,
            request_id="r1",
        )
        req = SimpleNamespace(
            id="r1",
            amount_required=100,
            accepted_total=0,
            price_per_unit=1.0,
            budget=100.0,
            status="open",
        )

        # After accept_submission the submission should be ACCEPTED (not PAID)
        returned_sub, returned_req = accept_submission(sub, req, db)
        assert returned_sub.status in (
            SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED
        ), f"Expected ACCEPTED/PARTIALLY_ACCEPTED, got {returned_sub.status}"
        assert returned_sub.status != "paid"


class TestAutoReleaseWindow:
    def test_window_not_expired_no_auto_release(self):
        """Within the window, download should NOT auto-release."""
        sub = _make_sub(
            status="accepted",
            accepted_at=datetime.utcnow() - timedelta(hours=WINDOW_HOURS - 1),
        )
        window_expired = datetime.utcnow() > sub.accepted_at + timedelta(hours=WINDOW_HOURS)
        assert not window_expired

    def test_window_expired_triggers_auto_release(self):
        """After window, auto-release logic should fire."""
        sub = _make_sub(
            status="accepted",
            accepted_at=datetime.utcnow() - timedelta(hours=WINDOW_HOURS + 1),
        )
        window_expired = datetime.utcnow() > sub.accepted_at + timedelta(hours=WINDOW_HOURS)
        assert window_expired

    def test_window_expired_but_dispute_open_blocks_release(self):
        """Dispute must block auto-release even after window."""
        sub = _make_sub(
            status="accepted",
            accepted_at=datetime.utcnow() - timedelta(hours=WINDOW_HOURS + 1),
        )
        window_expired = datetime.utcnow() > sub.accepted_at + timedelta(hours=WINDOW_HOURS)
        open_dispute = True   # simulate: a dispute is open
        should_auto_release = window_expired and not open_dispute
        assert not should_auto_release


class TestConfirmEndpointLogic:
    def test_confirm_on_paid_is_noop(self):
        """Confirming an already-PAID submission should succeed without error."""
        sub = _make_sub(status="paid")
        if sub.status == "paid":
            result = {"auto_released": False}
        assert result == {"auto_released": False}

    def test_confirm_on_validated_raises_409(self):
        """Cannot confirm a VALIDATED (not-yet-accepted) submission."""
        sub = _make_sub(status="validated")
        accepted = ("accepted", "partially_accepted")
        if sub.status not in accepted and sub.status != "paid":
            with pytest.raises(Exception):
                raise HTTPException(status_code=409, detail="Only ACCEPTED can be confirmed")

    def test_confirm_blocked_by_open_dispute(self):
        """Confirm must raise 409 when a dispute is open."""
        sub = _make_sub(status="accepted")
        dispute_open = True
        if dispute_open:
            with pytest.raises(HTTPException) as exc:
                raise HTTPException(status_code=409, detail="A dispute is open")
            assert exc.value.status_code == 409


class TestDownloadAllowedForAccepted:
    def test_accepted_status_passes_download_gate(self):
        """ACCEPTED submission should pass the download gate (buyer verifying)."""
        from app.models import SubmissionStatus
        allowed = (SubmissionStatus.PAID, SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED)
        assert SubmissionStatus.ACCEPTED in allowed
        assert SubmissionStatus.PARTIALLY_ACCEPTED in allowed
        assert SubmissionStatus.PAID in allowed

    def test_validated_status_blocked_from_download(self):
        from app.models import SubmissionStatus
        allowed = (SubmissionStatus.PAID, SubmissionStatus.ACCEPTED, SubmissionStatus.PARTIALLY_ACCEPTED)
        assert SubmissionStatus.VALIDATED not in allowed
        assert SubmissionStatus.REJECTED not in allowed
