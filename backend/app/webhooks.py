# app/webhooks.py
#
# Stripe webhook handler.  Verify the signature (when STRIPE_WEBHOOK_SECRET is set),
# then reconcile ledger state.  Never mutate state based on client-side callbacks alone —
# only the webhook is authoritative.

import json
import os

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProcessedStripeEvent

router = APIRouter()


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    if secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed webhook payload")
    else:
        # Dev mode — no signature check
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed payload")

    # construct_event (signed path) returns a Stripe Event object, not a dict, so
    # `.get(...)` would AttributeError. Normalize once so both paths use dict access.
    if not isinstance(event, dict):
        event = event.to_dict()

    event_type = event.get("type", "")
    event_id = event.get("id", "")

    # Dedup: Stripe redelivers on non-2xx responses. Skip if already processed.
    if event_id:
        already = db.query(ProcessedStripeEvent).filter(
            ProcessedStripeEvent.event_id == event_id
        ).first()
        if already:
            return {"received": True, "type": event_type, "duplicate": True}

    # Reconciliation stubs — extend as Stripe integration deepens
    if event_type == "payment_intent.succeeded":
        pass  # Escrow confirmed — no action needed (we record on API call, not webhook)
    elif event_type == "transfer.paid":
        pass  # Release confirmed
    elif event_type == "charge.refunded":
        pass  # Refund confirmed

    # Persist processed event so redeliveries are no-ops
    if event_id:
        db.add(ProcessedStripeEvent(event_id=event_id, event_type=event_type))
        db.commit()

    return {"received": True, "type": event_type}
