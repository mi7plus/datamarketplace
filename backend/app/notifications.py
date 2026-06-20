# app/notifications.py
#
# Out-of-band notification stub. In production wire this to an email/SMS provider;
# for now it logs at WARNING so security-relevant notices (e.g. a payout-account
# change) are at least recorded and alert-able. Kept side-effect-free and import-light.

import logging

logger = logging.getLogger("notifications")


def notify(user, subject: str, body: str) -> None:
    email = getattr(user, "email", "?")
    logger.warning("NOTIFY to=%s | %s | %s", email, subject, body)
