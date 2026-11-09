"""Core data model and validation for aznotify.

Pure Python — no Azure SDK imports here, so this module is trivially
testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

CHANNELS = ("email", "sms", "push")

MAX_MESSAGE_LENGTH = 1000
MAX_SUBJECT_LENGTH = 200
MIN_PUSH_TOKEN_LENGTH = 8

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# E.164: leading +, country code, 8-15 digits total after the +.
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class ValidationError(ValueError):
    """Raised when a notification payload fails validation.

    Carries every problem found, so the HTTP trigger can return them all
    in one 400 response instead of failing on the first one.
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class NotificationRequest:
    """A validated request to send one notification."""

    recipient: str
    channel: str
    message: str
    subject: str | None = None


@dataclass
class Notification:
    """A validated request plus the queue bookkeeping around it."""

    id: str
    recipient: str
    channel: str
    message: str
    subject: str | None = None
    attempts: int = 0
    enqueued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recipient": self.recipient,
            "channel": self.channel,
            "message": self.message,
            "subject": self.subject,
            "attempts": self.attempts,
            "enqueued_at": self.enqueued_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        return cls(
            id=str(data["id"]),
            recipient=str(data["recipient"]),
            channel=str(data["channel"]),
            message=str(data["message"]),
            subject=data.get("subject"),
            attempts=int(data.get("attempts", 0)),
            enqueued_at=str(data.get("enqueued_at", "")),
        )

    @classmethod
    def new(cls, request: NotificationRequest) -> "Notification":
        return cls(
            id=str(uuid4()),
            recipient=request.recipient,
            channel=request.channel,
            message=request.message,
            subject=request.subject,
        )


def _validate_recipient(channel: str, recipient: object, errors: list[str]) -> None:
    if not isinstance(recipient, str) or not recipient.strip():
        errors.append("recipient is required and must be a non-empty string")
        return
    recipient = recipient.strip()
    if channel == "email" and not _EMAIL_RE.match(recipient):
        errors.append(f"recipient {recipient!r} is not a valid email address")
    elif channel == "sms" and not _PHONE_RE.match(recipient):
        errors.append(
            f"recipient {recipient!r} is not a valid phone number "
            "(expected E.164, e.g. +14165551234)"
        )
    elif channel == "push" and len(recipient) < MIN_PUSH_TOKEN_LENGTH:
        errors.append("recipient for channel 'push' must be a device token "
                      f"of at least {MIN_PUSH_TOKEN_LENGTH} characters")


def validate_payload(data: object) -> NotificationRequest:
    """Validate a decoded JSON body; return a NotificationRequest or raise.

    Raises:
        ValidationError: with one entry per problem found.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValidationError(["request body must be a JSON object"])

    channel = data.get("channel")
    if not isinstance(channel, str) or channel not in CHANNELS:
        errors.append(f"channel must be one of {', '.join(CHANNELS)}")
        channel = None  # recipient checks that depend on channel are skipped

    if channel is not None:
        _validate_recipient(channel, data.get("recipient"), errors)
    elif not isinstance(data.get("recipient"), str) or not str(data.get("recipient")).strip():
        errors.append("recipient is required and must be a non-empty string")

    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        errors.append("message is required and must be a non-empty string")
    elif len(message) > MAX_MESSAGE_LENGTH:
        errors.append(f"message must be at most {MAX_MESSAGE_LENGTH} characters")

    subject = data.get("subject")
    if subject is not None:
        if not isinstance(subject, str):
            errors.append("subject must be a string when provided")
        elif len(subject) > MAX_SUBJECT_LENGTH:
            errors.append(f"subject must be at most {MAX_SUBJECT_LENGTH} characters")

    if errors:
        raise ValidationError(errors)

    return NotificationRequest(
        recipient=str(data["recipient"]).strip(),
        channel=str(channel),
        message=str(message).strip(),
        subject=str(subject) if isinstance(subject, str) else None,
    )
