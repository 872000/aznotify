"""Queue-trigger processing: deliver one queued notification.

This is the decision-making core of the queue trigger, kept free of Azure
SDK types so it can be unit-tested with plain fakes:

- unparseable / invalid message  -> dropped (logged, no retry: it will
  never become valid)
- sender succeeds               -> SENT
- transient sender failure     -> RETRY while attempts remain, otherwise
  the message is handed to ``dead_letter`` and reported DEAD_LETTERED
- permanent sender failure     -> DEAD_LETTERED immediately
- unexpected exception         -> treated as transient (RETRY / dead-letter)

The Azure queue trigger (function_app.py) raises on RETRY so the
Functions runtime redelivers the message, up to ``maxDequeueCount``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum

from .models import Notification, ValidationError, validate_payload
from .queue import (
    MAX_ATTEMPTS,
    build_queue_message,
    parse_queue_message,
    should_retry,
    with_attempts,
)
from .senders import (
    NotificationSender,
    SenderPermanentError,
    SenderTransientError,
    get_sender,
)

logger = logging.getLogger(__name__)


class Outcome(Enum):
    SENT = "sent"
    RETRY = "retry"
    DEAD_LETTERED = "dead_lettered"
    DROPPED_INVALID = "dropped_invalid"


def _dead_letter(
    notification: Notification,
    dead_letter: Callable[[str], None] | None,
) -> None:
    if dead_letter is None:
        logger.error(
            "no dead-letter handler configured; dropping notification %s "
            "after %d attempts",
            notification.id,
            notification.attempts,
        )
        return
    dead_letter(build_queue_message(notification))


def process_queued_message(
    raw: str | bytes,
    sender_factory: Callable[[str], NotificationSender] | None = None,
    dead_letter: Callable[[str], None] | None = None,
) -> tuple[Outcome, Notification | None]:
    """Process one raw queue message body.

    Returns ``(outcome, notification)``; ``notification`` is ``None`` when
    the message could not even be parsed into one.
    """
    if sender_factory is None:
        # Resolved here (not as a default argument) so tests and the
        # Functions host always see the current get_sender.
        sender_factory = get_sender
    try:
        notification = parse_queue_message(raw)
    except ValueError as exc:
        logger.warning("dropping unparseable queue message: %s", exc)
        return Outcome.DROPPED_INVALID, None

    # Defence in depth: the HTTP trigger already validated, but a message
    # could have been enqueued by anything else.
    try:
        validate_payload(
            {
                "recipient": notification.recipient,
                "channel": notification.channel,
                "message": notification.message,
                "subject": notification.subject,
            }
        )
    except ValidationError as exc:
        logger.warning(
            "dropping invalid queued notification %s: %s", notification.id, exc
        )
        return Outcome.DROPPED_INVALID, notification

    sender = sender_factory(notification.channel)
    try:
        result = sender.send(notification)
    except SenderPermanentError as exc:
        logger.error(
            "permanent send failure for %s; dead-lettering: %s",
            notification.id,
            exc,
        )
        _dead_letter(notification, dead_letter)
        return Outcome.DEAD_LETTERED, notification
    except SenderTransientError as exc:
        return _handle_transient(notification, dead_letter, exc)
    except Exception as exc:  # noqa: BLE001 — unknown failures are retried
        logger.exception("unexpected sender error for %s: %s", notification.id, exc)
        return _handle_transient(notification, dead_letter, exc)

    logger.info(
        "notification %s sent via %s (message %s)",
        notification.id,
        result.provider,
        result.message_id,
    )
    return Outcome.SENT, notification


def _handle_transient(
    notification: Notification,
    dead_letter: Callable[[str], None] | None,
    exc: Exception,
) -> tuple[Outcome, Notification]:
    attempts = notification.attempts + 1
    bumped = with_attempts(notification, attempts)
    if should_retry(attempts):
        logger.warning(
            "transient send failure for %s (attempt %d/%d); retrying: %s",
            notification.id,
            attempts,
            MAX_ATTEMPTS,
            exc,
        )
        return Outcome.RETRY, bumped
    logger.error(
        "transient send failure for %s after %d attempts; dead-lettering: %s",
        notification.id,
        attempts,
        exc,
    )
    _dead_letter(bumped, dead_letter)
    return Outcome.DEAD_LETTERED, bumped
