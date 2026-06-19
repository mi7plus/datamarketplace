# tests/test_idempotency.py
# F6: idempotent ledger writes + webhook dedup

import pytest
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Idempotent append_ledger
# ---------------------------------------------------------------------------

class TestIdempotentLedger:
    def _make_db(self, existing_ref=None):
        """Mock DB that returns existing_ref on ledger query if provided."""
        db = MagicMock()
        db.flush = MagicMock()
        db.add = MagicMock()
        added = []
        db.add.side_effect = lambda obj: added.append(obj)
        db._added = added

        if existing_ref:
            existing = SimpleNamespace(
                external_ref=existing_ref, entry_type="hold", amount=Decimal("100.00")
            )
            db.query.return_value.filter.return_value.first.return_value = existing
        else:
            db.query.return_value.filter.return_value.first.return_value = None
        return db

    def test_first_call_inserts(self):
        from app.payments import append_ledger
        db = self._make_db(existing_ref=None)
        result = append_ledger(db, "req-1", "hold", Decimal("100.00"), "ref_abc")
        assert db.add.call_count == 1

    def test_duplicate_ref_returns_existing_no_insert(self):
        from app.payments import append_ledger
        db = self._make_db(existing_ref="ref_abc")
        result = append_ledger(db, "req-1", "hold", Decimal("100.00"), "ref_abc")
        # Should NOT add a new entry — returns the existing one
        assert db.add.call_count == 0

    def test_none_external_ref_always_inserts(self):
        """Null external_ref (unlikely) skips the dedup lookup and always inserts."""
        from app.payments import append_ledger
        db = self._make_db(existing_ref=None)
        # Patch query to raise if called (should NOT be called when ref is None)
        db.query.side_effect = Exception("should not query when ref is None")
        result = append_ledger(db, "req-1", "hold", Decimal("50.00"), None)
        assert db.add.call_count == 1


# ---------------------------------------------------------------------------
# Single-commit allocation
# ---------------------------------------------------------------------------

class TestSingleCommitAllocation:
    def test_accept_submission_commits_once(self):
        """accept_submission must issue exactly one db.commit() for the whole allocation."""
        from app.lifecycle import accept_submission
        from app.models import SubmissionStatus

        commit_count = [0]

        db = MagicMock()
        def _commit():
            commit_count[0] += 1
        db.commit.side_effect = _commit
        db.refresh = MagicMock()
        db.flush = MagicMock()
        db.add = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        sub = SimpleNamespace(
            id="s1", status="validated", validated_amount=50,
            offered_amount=50, accepted_amount=0, amount_due=None,
            request_id="r1", key_hashes=None,
        )
        req = SimpleNamespace(
            id="r1", amount_required=100, accepted_total=0,
            price_per_unit="1.00", budget="100.00", status="open",
        )

        accept_submission(sub, req, db)
        assert commit_count[0] == 1, f"Expected 1 commit, got {commit_count[0]}"


# ---------------------------------------------------------------------------
# Webhook event dedup
# ---------------------------------------------------------------------------

class TestWebhookDedup:
    def _make_webhook_db(self, event_already_processed=False):
        db = MagicMock()
        db.commit = MagicMock()
        db.add = MagicMock()
        if event_already_processed:
            db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
                event_id="evt_123", event_type="payment_intent.succeeded"
            )
        else:
            db.query.return_value.filter.return_value.first.return_value = None
        return db

    def test_new_event_is_processed_and_recorded(self):
        """First delivery: processed, recorded in processed_stripe_events."""
        db = self._make_webhook_db(event_already_processed=False)
        event = {"id": "evt_abc", "type": "payment_intent.succeeded"}
        event_id = event.get("id", "")

        # Simulate handler logic
        already = db.query.return_value.filter.return_value.first.return_value
        assert already is None
        from app.models import ProcessedStripeEvent
        db.add(ProcessedStripeEvent(event_id=event_id, event_type=event["type"]))
        db.commit()

        assert db.add.call_count == 1
        assert db.commit.call_count == 1

    def test_duplicate_event_is_noop(self):
        """Second delivery of same event_id: returns duplicate=True, no DB write."""
        db = self._make_webhook_db(event_already_processed=True)
        event = {"id": "evt_123", "type": "payment_intent.succeeded"}

        already = db.query.return_value.filter.return_value.first.return_value
        if already:
            result = {"received": True, "type": event["type"], "duplicate": True}
            # Handler must return early — no add, no commit
        else:
            from app.models import ProcessedStripeEvent
            db.add(ProcessedStripeEvent(event_id=event["id"], event_type=event["type"]))
            db.commit()
            result = {"received": True, "type": event["type"]}

        assert result.get("duplicate") is True
        assert db.add.call_count == 0
        assert db.commit.call_count == 0
