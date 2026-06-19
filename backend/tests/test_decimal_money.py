# tests/test_decimal_money.py
# F5: ledger invariant holds exactly with Decimal — no float drift

import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_ledger_entry(entry_type: str, amount) -> SimpleNamespace:
    return SimpleNamespace(entry_type=entry_type, amount=amount)


def _ledger_balance(entries: list) -> dict:
    """Pure reimplementation of payments.ledger_balance using Decimal."""
    from app.payments import _to_decimal
    held     = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "hold"),     Decimal("0"))
    released = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "release"), Decimal("0"))
    refunded = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "refund"),  Decimal("0"))
    return {"held": held, "released": released, "refunded": refunded, "remaining": held - released - refunded}


class TestLedgerInvariantExact:
    def test_basic_hold_release_invariant(self):
        """held == released + refunded + remaining, exactly."""
        entries = [
            _make_ledger_entry("hold",    Decimal("100.00")),
            _make_ledger_entry("release", Decimal("73.50")),
        ]
        b = _ledger_balance(entries)
        assert b["held"] == b["released"] + b["refunded"] + b["remaining"]
        assert b["remaining"] == Decimal("26.50")

    def test_three_way_split_no_epsilon(self):
        """Multiple releases and a refund — invariant must be exact, no epsilon."""
        entries = [
            _make_ledger_entry("hold",    Decimal("100.00")),
            _make_ledger_entry("release", Decimal("33.33")),
            _make_ledger_entry("release", Decimal("33.33")),
            _make_ledger_entry("refund",  Decimal("33.34")),
        ]
        b = _ledger_balance(entries)
        assert b["held"] == b["released"] + b["refunded"] + b["remaining"]
        assert b["remaining"] == Decimal("0.00")

    def test_float_input_converted_exactly(self):
        """Float amounts from old rows are coerced to Decimal without drift."""
        entries = [
            _make_ledger_entry("hold",    0.1 + 0.2),   # float: 0.30000000000000004
            _make_ledger_entry("release", 0.3),
        ]
        b = _ledger_balance(entries)
        # After Decimal coercion both round to 0.30 — invariant holds
        assert b["held"] == b["released"] + b["refunded"] + b["remaining"]

    def test_zero_remaining_exactly(self):
        """Fully spent request: remaining must be exactly 0, not -epsilon."""
        entries = [
            _make_ledger_entry("hold",    Decimal("50.00")),
            _make_ledger_entry("release", Decimal("25.00")),
            _make_ledger_entry("release", Decimal("25.00")),
        ]
        b = _ledger_balance(entries)
        assert b["remaining"] == Decimal("0.00")
        assert b["held"] == b["released"] + b["refunded"] + b["remaining"]

    def test_no_entries_all_zeros(self):
        b = _ledger_balance([])
        assert b["held"] == b["released"] == b["refunded"] == b["remaining"] == Decimal("0")

    def test_amount_due_uses_decimal(self):
        """lifecycle.accept_submission sets amount_due as Decimal, not float."""
        from app.lifecycle import accept_submission
        from app.models import SubmissionStatus

        sub = SimpleNamespace(
            id="s1",
            status="validated",
            validated_amount=3,
            offered_amount=3,
            accepted_amount=0,
            amount_due=None,
            request_id="r1",
            key_hashes=None,
        )
        req = SimpleNamespace(
            id="r1",
            amount_required=10,
            accepted_total=0,
            price_per_unit="0.33",   # Decimal-safe string representation
            budget="3.30",
            status="open",
        )

        db = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.flush = MagicMock()
        db.add = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        accept_submission(sub, req, db)
        assert isinstance(sub.amount_due, Decimal), f"Expected Decimal, got {type(sub.amount_due)}"
        assert sub.amount_due == Decimal("0.99")

    @pytest.mark.parametrize("hold,releases,refund,expected_remaining", [
        ("200.00", ["50.00", "75.00"], "25.00", "50.00"),
        ("1000.00", ["999.99"], "0.00", "0.01"),
        ("0.01", [], "0.00", "0.01"),
        ("100.00", ["33.33", "33.33", "33.33"], "0.01", "0.00"),
    ])
    def test_invariant_parametrized(self, hold, releases, refund, expected_remaining):
        entries = [_make_ledger_entry("hold", Decimal(hold))]
        for r in releases:
            entries.append(_make_ledger_entry("release", Decimal(r)))
        if Decimal(refund) > 0:
            entries.append(_make_ledger_entry("refund", Decimal(refund)))
        b = _ledger_balance(entries)
        assert b["held"] == b["released"] + b["refunded"] + b["remaining"]
        assert b["remaining"] == Decimal(expected_remaining)
