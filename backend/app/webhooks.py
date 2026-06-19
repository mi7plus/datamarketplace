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

    event_type = event.get("type", "")

    # Phase 5 reconciliation stubs — extend as Stripe integration deepens
    if event_type == "payment_intent.succeeded":
        pass  # Escrow confirmed — no action needed (we record on API call, not webhook)
    elif event_type == "transfer.paid":
        pass  # Release confirmed
    elif event_type == "charge.refunded":
        pass  # Refund confirmed

    return {"received": True, "type": event_type}
