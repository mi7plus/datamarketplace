# tests/test_payments.py
# Ledger invariant: held == released + refunded + remaining (always)

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.payments import FakePaymentProvider, ledger_balance, append_ledger
from app.models import Ledger


def fake_request(budget=1000.0):
    return SimpleNamespace(
        id=uuid4(),
        budget=budget,
        accepted_total=0,
        amount_required=10_000,
        price_per_unit=0.1,
    )


def fake_submission(amount_due=100.0, request_id=None):
    return SimpleNamespace(
        id=uuid4(),
        request_id=request_id or uuid4(),
        amount_due=amount_due,
        provider_id=uuid4(),
    )


def fake_db_with_ledger():
    """Returns a mock db that stores Ledger entries and supports ledger queries."""
    entries: list[Ledger] = []

    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()

    def add(obj):
        if isinstance(obj, Ledger):
            entries.append(obj)
    db.add = add

    def flush():
        pass
    db.flush = flush

    # Support ledger_balance query: db.query(Ledger).filter(...).all()
    class FakeQuery:
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def all(self): return entries

    db.query = lambda model: FakeQuery() if model is Ledger else MagicMock()
    db._entries = entries
    return db


class TestFakePaymentProvider:
    def setup_method(self):
        self.provider = FakePaymentProvider()

    def test_hold_creates_ledger_entry(self):
        req = fake_request(budget=500.0)
        db = fake_db_with_ledger()
        ref = self.provider.hold_escrow(req, db)
        assert ref.startswith("fake_hold_")
        assert len(db._entries) == 1
        assert db._entries[0].entry_type == "hold"
        assert db._entries[0].amount == 500.0

    def test_release_creates_ledger_entry(self):
        req_id = uuid4()
        sub = fake_submission(amount_due=80.0, request_id=req_id)
        db = fake_db_with_ledger()
        ref = self.provider.release_to_provider(sub, db)
        assert ref.startswith("fake_release_")
        assert db._entries[0].entry_type == "release"
        assert db._entries[0].amount == 80.0

    def test_refund_creates_ledger_entry(self):
        req = fake_request(budget=200.0)
        db = fake_db_with_ledger()
        ref = self.provider.refund_to_buyer(req, 120.0, db)
        assert ref.startswith("fake_refund_")
        assert db._entries[0].amount == 120.0

    def test_zero_refund_skips_entry(self):
        req = fake_request()
        db = fake_db_with_ledger()
        ref = self.provider.refund_to_buyer(req, 0.0, db)
        assert ref == "fake_refund_zero"
        assert len(db._entries) == 0


class TestLedgerInvariant:
    """
    Invariant: held == released + refunded + remaining — always.
    For any sequence of money operations, the books must balance.
    """

    def _run_scenario(self, budget, releases, refund):
        """Build a ledger with one hold, N releases, one refund; verify invariant."""
        req_id = uuid4()
        db = fake_db_with_ledger()
        provider = FakePaymentProvider()

        req = fake_request(budget=budget)
        req.id = req_id
        provider.hold_escrow(req, db)

        for amount in releases:
            sub = fake_submission(amount_due=amount, request_id=req_id)
            provider.release_to_provider(sub, db)

        if refund > 0:
            provider.refund_to_buyer(req, refund, db)

        from decimal import Decimal
        bal = ledger_balance(db, req_id)
        # ledger_balance now returns Decimal — coerce budget for comparison
        d_budget = Decimal(str(budget)).quantize(Decimal("0.01"))
        assert bal["held"] == d_budget, f"held {bal['held']} != budget {d_budget}"
        total_out = bal["released"] + bal["refunded"] + bal["remaining"]
        assert total_out == bal["held"], (
            f"invariant broken: {bal['held']} held != "
            f"{bal['released']} released + {bal['refunded']} refunded + {bal['remaining']} remaining"
        )

    def test_full_release_no_refund(self):
        self._run_scenario(budget=1000.0, releases=[400.0, 600.0], refund=0.0)

    def test_partial_release_with_refund(self):
        self._run_scenario(budget=1000.0, releases=[400.0], refund=600.0)

    def test_expired_no_acceptances(self):
        self._run_scenario(budget=500.0, releases=[], refund=500.0)

    def test_completed_with_rounding_remainder(self):
        # 3 × $3.333 = $9.999; refund 0.001
        self._run_scenario(budget=10.0, releases=[3.33, 3.33, 3.33], refund=0.01)

    def test_single_provider_full(self):
        self._run_scenario(budget=200.0, releases=[200.0], refund=0.0)
