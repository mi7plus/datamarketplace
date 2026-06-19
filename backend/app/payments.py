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

import stripe
from sqlalchemy.orm import Session

from app.models import DataRequest, Submission, Ledger, UserAuth


# ---------------------------------------------------------------------------
# Ledger helper — all money ops write here (append-only)
# ---------------------------------------------------------------------------

def append_ledger(
    db: Session,
    request_id,
    entry_type: str,     # "hold" | "release" | "refund"
    amount: float,
    external_ref: str,
    submission_id=None,
) -> Ledger:
    entry = Ledger(
        request_id=request_id,
        submission_id=submission_id,
        entry_type=entry_type,
        amount=round(amount, 2),
        external_ref=external_ref,
    )
    db.add(entry)
    db.flush()
    return entry


def ledger_balance(db: Session, request_id) -> dict:
    """Return {held, released, refunded, remaining} for a request."""
    entries = db.query(Ledger).filter(Ledger.request_id == str(request_id)).all()
    held = sum(e.amount for e in entries if e.entry_type == "hold")
    released = sum(e.amount for e in entries if e.entry_type == "release")
    refunded = sum(e.amount for e in entries if e.entry_type == "refund")
    return {
        "held": round(held, 2),
        "released": round(released, 2),
        "refunded": round(refunded, 2),
        "remaining": round(held - released - refunded, 2),
    }


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class PaymentProvider(ABC):
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


# ---------------------------------------------------------------------------
# Fake provider — safe for testing and development
# ---------------------------------------------------------------------------

class FakePaymentProvider(PaymentProvider):
    """No real charges — just ledger entries. Replace with StripePaymentProvider in production."""

    def hold_escrow(self, request: DataRequest, db: Session) -> str:
        ref = f"fake_hold_{uuid.uuid4().hex[:12]}"
        append_ledger(db, request.id, "hold", request.budget or 0.0, ref)
        return ref

    def release_to_provider(self, submission: Submission, db: Session) -> str:
        ref = f"fake_release_{uuid.uuid4().hex[:12]}"
        append_ledger(
            db, submission.request_id, "release",
            submission.amount_due or 0.0, ref,
            submission_id=submission.id,
        )
        return ref

    def refund_to_buyer(self, request: DataRequest, amount: float, db: Session) -> str:
        if amount <= 0:
            return "fake_refund_zero"
        ref = f"fake_refund_{uuid.uuid4().hex[:12]}"
        append_ledger(db, request.id, "refund", amount, ref)
        return ref

    def create_connect_link(self, user: UserAuth, return_url: str, refresh_url: str) -> tuple[str, str]:
        acct_id = user.stripe_account_id or f"acct_fake_{uuid.uuid4().hex[:16]}"
        url = (
            f"https://connect.stripe.com/fake/onboarding"
            f"?account={acct_id}&return_url={return_url}"
        )
        return url, acct_id


# ---------------------------------------------------------------------------
# Real Stripe provider
# ---------------------------------------------------------------------------

class StripePaymentProvider(PaymentProvider):
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
        transfer = stripe.Transfer.create(
            amount=int((submission.amount_due or 0) * 100),
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
