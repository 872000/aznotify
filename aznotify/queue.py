"""Queue message helpers for aznotify.

The HTTP trigger serialises a :class:`~aznotify.models.Notification` to a
JSON string and puts it on the ``notifications`` queue; the queue trigger
reads it back. Everything here is pure JSON handling — no Azure SDK —
so it is testable offline.
"""

from __future__ import annotations

import json

from .models import Notification

NOTIFICATION_QUEUE_NAME = "notifications"
POISON_QUEUE_NAME = "notifications-poison"

#: Give up after this many delivery attempts; the message then goes to the
#: poison queue instead of being retried forever. Mirrors the
#: ``maxDequeueCount`` of 5 in host.json.
MAX_ATTEMPTS = 5


def build_queue_message(notification: Notification) -> str:
    """Serialise a notification into the JSON string placed on the queue."""
    return json.dumps(notification.to_dict())


def parse_queue_message(raw: str | bytes) -> Notification:
    """Deserialise a queue message body back into a Notification.

    Raises:
        ValueError: if the body is not valid JSON, or is missing the fields
            a Notification requires.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"queue message is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("queue message must be a JSON object")
    try:
        return Notification.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"queue message is missing required fields: {exc}") from exc


def with_attempts(notification: Notification, attempts: int) -> Notification:
    """Return a copy of ``notification`` with the attempt count updated."""
    return Notification(
        id=notification.id,
        recipient=notification.recipient,
        channel=notification.channel,
        message=notification.message,
        subject=notification.subject,
        attempts=attempts,
        enqueued_at=notification.enqueued_at,
    )


def should_retry(attempts: int) -> bool:
    """True while another delivery attempt is still allowed."""
    return attempts < MAX_ATTEMPTS
