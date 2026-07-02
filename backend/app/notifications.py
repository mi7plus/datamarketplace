# app/notifications.py
#
# Out-of-band notification stub. In production wire this to an email/SMS provider;
# for now it logs at WARNING so security-relevant notices (e.g. a payout-account
# change) are at least recorded and alert-able. Kept side-effect-free and import-light.

import logging

logger = logging.getLogger("notifications")


def notify(user, subject: str, body: str) -> None:
    """Send an out-of-band notice to a user. Delegates to the configured mailer
    (LogMailer in dev/CI → logs; SesMailer in prod → real email). Best-effort:
    a mail failure is logged, never raised, so it can't break the caller's flow."""
    email = getattr(user, "email", None)
    if not email:
        logger.warning("NOTIFY skipped (no email) | %s | %s", subject, body)
        return
    notify_address(email, subject, body)


def notify_address(email: str | None, subject: str, body: str) -> None:
    """Send an out-of-band notice to a fixed address (e.g. an internal inbox), rather
    than to a user record. Same best-effort contract as notify()."""
    if not email:
        logger.warning("NOTIFY skipped (no address) | %s | %s", subject, body)
        return
    try:
        from app.mailer import get_mailer
        get_mailer().send(to=email, subject=subject, body=body)
    except Exception:
        logger.exception("NOTIFY failed to=%s | %s", email, subject)
