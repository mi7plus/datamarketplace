# app/contact.py
#
# Contact form intake (U2). Rate-limited, honeypot + time-trap protected, GDPR
# consent required. Routes by reason; stores the message and fires an out-of-band
# notice. No raw inbox is exposed to the client.

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ContactMessage
from app.ratelimit import rate_limit
from app.audit import client_ip
from app.notifications import notify_address

import os

router = APIRouter()
_contact_rl = rate_limit("contact", limit=5, window_seconds=60)

# Where contact-form submissions are emailed. Delivery depends on a live mailer
# (MAILER=ses); until then notify_address just logs. Messages are always persisted
# to ContactMessage regardless, so nothing is lost.
CONTACT_INBOX = os.getenv("CONTACT_INBOX", "contact@rowbound.com")

REASONS = {"buyer", "supplier", "press", "support"}


class ContactIn(BaseModel):
    name: str
    email: EmailStr
    org: str | None = None
    reason: str
    message: str
    consent: bool = False
    company_website: str | None = None   # honeypot — humans never see this field
    elapsed_ms: int | None = None        # client-measured time-to-submit


@router.post("/")
def submit_contact(
    data: ContactIn,
    request: Request,
    db: Session = Depends(get_db),
    _rl=Depends(_contact_rl),
):
    # Bot traps: a filled honeypot or an implausibly fast submit looks successful
    # but is silently dropped (don't tell the bot it was caught).
    if data.company_website:
        return {"ok": True}
    if data.elapsed_ms is not None and data.elapsed_ms < 2000:
        return {"ok": True}

    if not data.consent:
        raise HTTPException(status_code=422, detail="Please accept the privacy notice to continue")
    if data.reason not in REASONS:
        raise HTTPException(status_code=422, detail="Invalid reason")
    if not data.message.strip():
        raise HTTPException(status_code=422, detail="Message is required")

    msg = ContactMessage(
        name=data.name.strip()[:200],
        email=str(data.email),
        org=((data.org or "").strip()[:200] or None),
        reason=data.reason,
        message=data.message.strip()[:5000],
        ip=client_ip(request),
    )
    db.add(msg)
    db.commit()

    notify_address(
        CONTACT_INBOX,
        f"Contact [{data.reason}] from {msg.name}",
        f"From: {msg.name} <{msg.email}>\n"
        f"Org: {msg.org or '—'}\n"
        f"Reason: {msg.reason}\n\n"
        f"{msg.message}\n\n"
        f"— reply directly to {msg.email}",
    )
    return {"ok": True}
