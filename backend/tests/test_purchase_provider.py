# tests/test_purchase_provider.py
# Phase 4 completion: catalog purchases settle through the PaymentProvider
# abstraction. Demo mode (FakePaymentProvider) needs no Stripe account; real mode
# (StripePaymentProvider) requires a connected supplier account.

from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import MagicMock

from app.payments import FakePaymentProvider, StripePaymentProvider, purchase_balance
from app.models import Ledger


def _fake_db_with_ledger():
    entries: list[Ledger] = []
    db = MagicMock()
    db.add = lambda obj: entries.append(obj) if isinstance(obj, Ledger) else None
    db.flush = lambda: None

    last_ref = [None]

    class Q:
        def filter(self, *a):
            for arg in a:
                try:
                    v = arg.right.value
                    if v is not None:
                        last_ref[0] = v
                except Exception:
                    pass
            return self
        def all(self):
            return entries
        def first(self):
            ref = last_ref[0]
            return next((e for e in entries if getattr(e, "external_ref", None) == ref), None)

    db.query = lambda model: Q() if model is Ledger else MagicMock()
    db._entries = entries
    return db


def _purchase(amount="12.00"):
    return SimpleNamespace(id="p1", listing_id="l1", amount=Decimal(amount))


class TestDemoMode:
    def test_fake_provider_needs_no_connected_account(self):
        assert FakePaymentProvider.requires_connected_account is False

    def test_fake_hold_and_release_balance(self):
        db = _fake_db_with_ledger()
        p = _purchase("12.00")
        prov = FakePaymentProvider()
        prov.hold_purchase(p, db)
        prov.release_purchase(p, supplier=None, db=db)   # no supplier needed in demo
        bal = purchase_balance(db, "p1")
        assert bal["held"] == bal["released"] == Decimal("12.00")
        assert bal["remaining"] == Decimal("0")

    def test_fake_refs_are_deterministic(self):
        db = _fake_db_with_ledger()
        p = _purchase()
        prov = FakePaymentProvider()
        prov.hold_purchase(p, db)
        prov.hold_purchase(p, db)   # idempotent — same ref, no second row
        holds = [e for e in db._entries if e.entry_type == "hold"]
        assert len(holds) == 1


class TestRealModeGate:
    def test_stripe_requires_connected_account_flag(self):
        assert StripePaymentProvider.requires_connected_account is True

    def test_release_without_account_raises(self):
        prov = StripePaymentProvider.__new__(StripePaymentProvider)  # no API call
        try:
            prov.release_purchase(_purchase(), supplier=None, db=MagicMock())
            assert False, "expected ValueError"
        except ValueError:
            pass
