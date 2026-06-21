# app/payments.py
#
# Payment provider abstraction.
# FakePaymentProvider (default) records ledger entries but moves no real money.
# Set STRIPE_USE_REAL=true + STRIPE_SECRET_KEY to swap in StripePaymentProvider.
#
# Call sites never import the concrete class — always call get_payment_provider().

import os
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP

import stripe
from sqlalchemy.orm import Session

from app.models import DataRequest, Submission, Ledger, UserAuth


# ---------------------------------------------------------------------------
# Ledger helper — all money ops write here (append-only)
# ---------------------------------------------------------------------------

def _to_decimal(v) -> Decimal:
    """Coerce float/int/str/Decimal to Decimal(12,2)."""
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def append_ledger(
    db: Session,
    request_id,
    entry_type: str,     # "hold" | "release" | "refund"
    amount,
    external_ref: str,
    submission_id=None,
    purchase_id=None,
) -> Ledger:
    # Idempotency: if this external_ref was already recorded, return existing row.
    # Prevents double-recording on webhook redelivery or retry after partial failure.
    if external_ref:
        existing = db.query(Ledger).filter(Ledger.external_ref == external_ref).first()
        if existing:
            return existing
    entry = Ledger(
        request_id=request_id,
        submission_id=submission_id,
        purchase_id=purchase_id,
        entry_type=entry_type,
        amount=_to_decimal(amount),
        external_ref=external_ref,
    )
    db.add(entry)
    db.flush()
    return entry


def purchase_balance(db: Session, purchase_id) -> dict:
    """Same {held, released, refunded, remaining} as ledger_balance, keyed by a Purchase."""
    entries = db.query(Ledger).filter(Ledger.purchase_id == str(purchase_id)).all()
    held     = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "hold"),     Decimal("0"))
    released = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "release"), Decimal("0"))
    refunded = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "refund"),  Decimal("0"))
    return {"held": held, "released": released, "refunded": refunded,
            "remaining": held - released - refunded}


def ledger_balance(db: Session, request_id) -> dict:
    """Return {held, released, refunded, remaining} as exact Decimal values."""
    entries = db.query(Ledger).filter(Ledger.request_id == str(request_id)).all()
    held     = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "hold"),     Decimal("0"))
    released = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "release"), Decimal("0"))
    refunded = sum((_to_decimal(e.amount) for e in entries if e.entry_type == "refund"),  Decimal("0"))
    remaining = held - released - refunded
    return {
        "held":      held,
        "released":  released,
        "refunded":  refunded,
        "remaining": remaining,
    }


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class PaymentProvider(ABC):
    # True for real money providers: the supplier/provider must have a connected
    # payout account before funds can be released. False for the dev/demo Fake
    # provider, so the platform runs end-to-end with no Stripe setup.
    requires_connected_account: bool = False

    @abstractmethod
    def hold_escrow(self, request: DataRequest, db: Session) -> str:
        """Reserve request.budget from the buyer. Returns external_ref."""

    @abstractmethod
    def release_to_provider(self, submission: Submission, db: Session) -> str:
        """Transfer submission.amount_due to provider's connected account. Returns external_ref."""

    @abstractmethod
    def refund_to_buyer(self, request: DataRequest, amount: float, db: Session) -> str:
        """Refund `amount` of unspent escrow to the buyer. Returns external_ref."""

    @abstractmethod
    def create_connect_link(self, user: UserAuth, return_url: str, refresh_url: str) -> tuple[str, str]:
        """Return (onboarding_url, stripe_account_id) for provider Connect onboarding."""

    # --- Mode 2 (catalog) purchase settlement ---

    @abstractmethod
    def hold_purchase(self, purchase, db: Session) -> str:
        """Charge the buyer purchase.amount. Returns external_ref."""

    @abstractmethod
    def release_purchase(self, purchase, supplier, db: Session) -> str:
        """Transfer purchase.amount to the supplier's connected account. Returns external_ref."""


# ---------------------------------------------------------------------------
# Fake provider — safe for testing and development
# ---------------------------------------------------------------------------

class FakePaymentProvider(PaymentProvider):
    """No real charges — just ledger entries. Replace with StripePaymentProvider in production."""

    def hold_escrow(self, request: DataRequest, db: Session) -> str:
        # Deterministic ref (keyed by request) so the unique Ledger.external_ref
        # constraint catches a double-hold exactly as Stripe's idempotency key would.
        ref = f"fake_hold_{request.id}"
        append_ledger(db, request.id, "hold", request.budget or 0.0, ref)
        return ref

    def release_to_provider(self, submission: Submission, db: Session) -> str:
        # Deterministic ref (keyed by submission) — mirrors Stripe's
        # idempotency_key=release_{submission.id}. A concurrent/duplicate release
        # produces the SAME ref, so append_ledger's idempotency check (and the
        # unique constraint) turn it into a no-op instead of a silent double-count.
        ref = f"fake_release_{submission.id}"
        append_ledger(
            db, submission.request_id, "release",
            submission.amount_due or 0.0, ref,
            submission_id=submission.id,
        )
        return ref

    def refund_to_buyer(self, request: DataRequest, amount: float, db: Session) -> str:
        if amount <= 0:
            return "fake_refund_zero"
        # Keyed by request + amount (in cents) to match StripePaymentProvider's
        # refund idempotency key and stay stable across retries of the same refund.
        ref = f"fake_refund_{request.id}_{int(round(float(amount) * 100))}"
        append_ledger(db, request.id, "refund", amount, ref)
        return ref

    def create_connect_link(self, user: UserAuth, return_url: str, refresh_url: str) -> tuple[str, str]:
        acct_id = user.stripe_account_id or f"acct_fake_{uuid.uuid4().hex[:16]}"
        url = (
            f"https://connect.stripe.com/fake/onboarding"
            f"?account={acct_id}&return_url={return_url}"
        )
        return url, acct_id

    def hold_purchase(self, purchase, db: Session) -> str:
        ref = f"fake_phold_{purchase.id}"
        append_ledger(db, None, "hold", purchase.amount or 0.0, ref, purchase_id=purchase.id)
        return ref

    def release_purchase(self, purchase, supplier, db: Session) -> str:
        ref = f"fake_prelease_{purchase.id}"
        append_ledger(db, None, "release", purchase.amount or 0.0, ref, purchase_id=purchase.id)
        return ref


# ---------------------------------------------------------------------------
# Real Stripe provider
# ---------------------------------------------------------------------------

class StripePaymentProvider(PaymentProvider):
    requires_connected_account = True

    def __init__(self, secret_key: str):
        stripe.api_key = secret_key

    def hold_escrow(self, request: DataRequest, db: Session) -> str:
        intent = stripe.PaymentIntent.create(
            amount=int((request.budget or 0) * 100),  # Stripe uses smallest currency unit
            currency="usd",
            capture_method="manual",
            metadata={"request_id": str(request.id)},
            idempotency_key=f"hold_{request.id}",
        )
        append_ledger(db, request.id, "hold", request.budget or 0.0, intent.id)
        return intent.id

    def release_to_provider(self, submission: Submission, db: Session) -> str:
        provider = db.get(UserAuth, str(submission.provider_id))
        if not provider or not provider.stripe_account_id:
            raise ValueError("Provider has no connected Stripe account — cannot release funds")
        # Transfer net of platform commission (the platform keeps the rest as its take).
        net = float(submission.amount_due or 0) - float(submission.commission_amount or 0)
        transfer = stripe.Transfer.create(
            amount=int(net * 100),
            currency="usd",
            destination=provider.stripe_account_id,
            metadata={
                "submission_id": str(submission.id),
                "request_id": str(submission.request_id),
            },
            idempotency_key=f"release_{submission.id}",
        )
        append_ledger(
            db, submission.request_id, "release",
            submission.amount_due or 0.0, transfer.id,
            submission_id=submission.id,
        )
        return transfer.id

    def refund_to_buyer(self, request: DataRequest, amount: float, db: Session) -> str:
        if amount <= 0:
            return "refund_zero"
        # Find the PaymentIntent from the hold entry
        hold_entry = (
            db.query(Ledger)
            .filter(Ledger.request_id == str(request.id), Ledger.entry_type == "hold")
            .first()
        )
        ref = f"stripe_refund_{uuid.uuid4().hex[:12]}"
        if hold_entry and hold_entry.external_ref:
            refund = stripe.Refund.create(
                payment_intent=hold_entry.external_ref,
                amount=int(amount * 100),
                idempotency_key=f"refund_{request.id}_{int(amount*100)}",
            )
            ref = refund.id
        append_ledger(db, request.id, "refund", amount, ref)
        return ref

    def create_connect_link(self, user: UserAuth, return_url: str, refresh_url: str) -> tuple[str, str]:
        if not user.stripe_account_id:
            account = stripe.Account.create(
                type="express",
                metadata={"user_id": str(user.id)},
            )
            acct_id = account.id
        else:
            acct_id = user.stripe_account_id
        link = stripe.AccountLink.create(
            account=acct_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )
        return link.url, acct_id

    def hold_purchase(self, purchase, db: Session) -> str:
        # Catalog data is delivered immediately, so capture the charge now.
        intent = stripe.PaymentIntent.create(
            amount=int((float(purchase.amount or 0)) * 100),
            currency="usd",
            capture_method="automatic",
            metadata={"purchase_id": str(purchase.id), "listing_id": str(purchase.listing_id)},
            idempotency_key=f"phold_{purchase.id}",
        )
        append_ledger(db, None, "hold", purchase.amount or 0.0, intent.id, purchase_id=purchase.id)
        return intent.id

    def release_purchase(self, purchase, supplier, db: Session) -> str:
        if not supplier or not supplier.stripe_account_id:
            raise ValueError("Supplier has no connected Stripe account — cannot release funds")
        net = float(purchase.amount or 0) - float(getattr(purchase, "commission_amount", 0) or 0)
        transfer = stripe.Transfer.create(
            amount=int(net * 100),
            currency="usd",
            destination=supplier.stripe_account_id,
            metadata={"purchase_id": str(purchase.id)},
            idempotency_key=f"prelease_{purchase.id}",
        )
        append_ledger(db, None, "release", purchase.amount or 0.0, transfer.id, purchase_id=purchase.id)
        return transfer.id


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        secret = os.getenv("STRIPE_SECRET_KEY", "")
        use_real = os.getenv("STRIPE_USE_REAL", "false").lower() == "true"
        if secret and use_real:
            _provider = StripePaymentProvider(secret)
        else:
            _provider = FakePaymentProvider()
    return _provider
