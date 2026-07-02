# app/mailer.py
#
# Pluggable transactional mailer (Social-login plan, Phase 1 prerequisite).
#
# Same pattern as PaymentProvider / KeyProvider: an ABC with a dev-default
# implementation (LogMailer — logs, sends nothing, so dev/CI need no mail infra)
# and a prod implementation (SesMailer — AWS SES). Selected by MAILER env
# (default "log"). get_mailer() is the singleton every caller uses.
#
# DEV/CI: MAILER unset -> LogMailer, so registration + notifications never depend on
# a real mail provider. PROD: MAILER=ses with MAIL_FROM set (a verified SES sender).
# NOTE: a new SES account is sandboxed (can only send to verified addresses) until
# you request production access — start that request early.

import os
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("mailer")


class Mailer(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email. Must not raise on the caller's happy path —
        callers treat mail as best-effort (a failed email never blocks the request)."""


class LogMailer(Mailer):
    """Dev/CI default: records the message at WARNING, sends nothing."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.warning("EMAIL (not sent — LogMailer) to=%s | %s | %s", to, subject, body)


class SesMailer(Mailer):
    """Prod: AWS SES. Credentials come from the task role (no static keys)."""

    def __init__(self):
        import boto3

        self._from = os.getenv("MAIL_FROM", "")
        self._client = boto3.client("ses", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))

    def send(self, to: str, subject: str, body: str) -> None:
        self._client.send_email(
            Source=self._from,
            Destination={"ToAddresses": [to]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
        )


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = SesMailer() if os.getenv("MAILER", "log").lower() == "ses" else LogMailer()
    return _mailer
