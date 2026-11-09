"""Pluggable notification senders for aznotify.

The queue trigger sends through the ``NotificationSender`` protocol, so a
real provider can be slotted in without touching the trigger code. The
default sender just logs to the console — safe to run anywhere, no
credentials, no cloud spend.

Real providers are present only as clearly-marked STUBS: they raise
``NotImplementedError`` with the exact configuration they would need, so
nobody mistakes them for working integrations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from .models import Notification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    """What a sender reports back after a successful send."""

    channel: str
    recipient: str
    message_id: str
    provider: str


class SenderError(Exception):
    """Base class for sender failures."""


class SenderTransientError(SenderError):
    """Temporary failure (rate limit, network blip) — safe to retry."""


class SenderPermanentError(SenderError):
    """Permanent failure (bad address, rejected content) — retrying is useless."""


class NotificationSender(Protocol):
    """Anything that can deliver a notification. Implement ``send``."""

    def send(self, notification: Notification) -> SendResult:
        ...


@dataclass
class ConsoleSender:
    """Default sender: logs the notification and records it in memory.

    Useful for local development and for tests. ``sent`` is instance state,
    so each sender has its own independent outbox.
    """

    sent: list[SendResult] = field(default_factory=list)

    def send(self, notification: Notification) -> SendResult:
        result = SendResult(
            channel=notification.channel,
            recipient=notification.recipient,
            message_id=f"console-{uuid4().hex[:12]}",
            provider="console",
        )
        self.sent.append(result)
        logger.info(
            "[console] %s -> %s (%s): %s",
            notification.channel,
            notification.recipient,
            result.message_id,
            notification.message,
        )
        return result


class SmtpEmailSender:
    """STUB — not implemented. Real email sending goes here.

    To implement: read SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD
    from the environment, connect with ``smtplib``, and send a MIME message
    to ``notification.recipient``. Raise ``SenderTransientError`` on
    connection failures and ``SenderPermanentError`` on 5xx rejections.
    """

    def send(self, notification: Notification) -> SendResult:
        raise NotImplementedError(
            "SmtpEmailSender is a stub: configure SMTP_HOST/SMTP_PORT/"
            "SMTP_USER/SMTP_PASSWORD and implement send() (see senders.py)."
        )


class TwilioSmsSender:
    """STUB — not implemented. Real SMS sending goes here.

    To implement: read TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
    TWILIO_FROM_NUMBER from the environment and call the Twilio Messages
    API for ``notification.recipient``. Map Twilio 429/5xx to
    ``SenderTransientError`` and invalid-number errors to
    ``SenderPermanentError``.
    """

    def send(self, notification: Notification) -> SendResult:
        raise NotImplementedError(
            "TwilioSmsSender is a stub: configure TWILIO_ACCOUNT_SID/"
            "TWILIO_AUTH_TOKEN/TWILIO_FROM_NUMBER and implement send() "
            "(see senders.py)."
        )


class FirebasePushSender:
    """STUB — not implemented. Real push sending goes here.

    To implement: read FIREBASE_CREDENTIALS (path to a service-account
    JSON file, never committed) from the environment, initialise the
    Firebase Admin SDK, and send to ``notification.recipient`` as a
    device token. Map unregistered-token errors to
    ``SenderPermanentError``.
    """

    def send(self, notification: Notification) -> SendResult:
        raise NotImplementedError(
            "FirebasePushSender is a stub: configure FIREBASE_CREDENTIALS "
            "and implement send() (see senders.py)."
        )


_SENDERS: dict[str, type] = {
    "console": ConsoleSender,
    "smtp": SmtpEmailSender,
    "twilio": TwilioSmsSender,
    "firebase": FirebasePushSender,
}


def get_sender(name: str | None = None) -> NotificationSender:
    """Return a sender by name.

    Defaults to the ``AZNOTIFY_SENDER`` environment variable, then
    ``"console"``. Unknown names raise ``ValueError`` — failing fast here
    beats silently dropping notifications.
    """
    resolved = (name or os.environ.get("AZNOTIFY_SENDER") or "console").lower()
    try:
        return _SENDERS[resolved]()
    except KeyError:
        raise ValueError(
            f"unknown sender {resolved!r}; expected one of "
            f"{', '.join(sorted(_SENDERS))}"
        ) from None
