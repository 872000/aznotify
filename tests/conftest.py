"""Shared fakes for the aznotify test suite.

Everything here is in-memory: no Azure services, no network, no
credentials. The HTTP trigger's enqueue step and the queue trigger's
dead-letter step are monkeypatched onto in-memory lists in the tests
that need them.
"""

from __future__ import annotations

import json

import azure.functions as func
import pytest

from aznotify.models import Notification, NotificationRequest
from aznotify.queue import build_queue_message
from aznotify.senders import (
    ConsoleSender,
    SendResult,
    SenderPermanentError,
    SenderTransientError,
)


def make_request(**overrides) -> NotificationRequest:
    payload = {
        "recipient": "parth@example.com",
        "channel": "email",
        "message": "Hello from aznotify!",
    }
    payload.update(overrides)
    return NotificationRequest(**payload)


def make_notification(**overrides) -> Notification:
    request_overrides = {
        key: value
        for key, value in overrides.items()
        if key in ("recipient", "channel", "message", "subject")
    }
    notification = Notification.new(make_request(**request_overrides))
    for key, value in overrides.items():
        if key not in request_overrides and hasattr(notification, key):
            object.__setattr__(notification, key, value)
    return notification


def make_http_request(body: object) -> func.HttpRequest:
    """Build a real azure.functions HttpRequest from a dict / raw string."""
    raw = body if isinstance(body, (str, bytes)) else json.dumps(body)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return func.HttpRequest(
        method="POST",
        url="/api/notify",
        headers={"Content-Type": "application/json"},
        body=raw,
    )


class FakeQueueMessage:
    """Duck-typed stand-in for azure.functions.QueueMessage."""

    def __init__(self, body: str | bytes) -> None:
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def get_body(self) -> bytes:
        return self._body


def queue_message_for(notification: Notification) -> FakeQueueMessage:
    return FakeQueueMessage(build_queue_message(notification))


class FakeSender:
    """Configurable sender: records sends, optionally fails on demand."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.sent: list[Notification] = []
        self.fail_with = fail_with

    def send(self, notification: Notification) -> SendResult:
        if self.fail_with is not None:
            raise self.fail_with
        result = SendResult(
            channel=notification.channel,
            recipient=notification.recipient,
            message_id="fake-123",
            provider="fake",
        )
        self.sent.append(notification)
        return result


@pytest.fixture
def console_sender() -> ConsoleSender:
    return ConsoleSender()


@pytest.fixture
def dead_letter_box() -> list[str]:
    return []


__all__ = [
    "FakeQueueMessage",
    "FakeSender",
    "SenderPermanentError",
    "SenderTransientError",
    "console_sender",
    "dead_letter_box",
    "make_http_request",
    "make_notification",
    "make_request",
    "queue_message_for",
]
