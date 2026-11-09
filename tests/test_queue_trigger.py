"""Tests for the queue trigger (function_app.queue_process) and the
processing core (aznotify.processing.process_queued_message).
"""

import json

import pytest

import function_app
from aznotify.processing import Outcome, process_queued_message
from aznotify.queue import MAX_ATTEMPTS, build_queue_message
from tests.conftest import (
    FakeQueueMessage,
    FakeSender,
    SenderPermanentError,
    SenderTransientError,
    make_notification,
    queue_message_for,
)


# --- processing core -------------------------------------------------------

def test_happy_path_sends_and_returns_sent():
    sender = FakeSender()
    outcome, notification = process_queued_message(
        build_queue_message(make_notification()),
        sender_factory=lambda _channel: sender,
    )
    assert outcome is Outcome.SENT
    assert len(sender.sent) == 1
    assert notification is not None


def test_unparseable_message_is_dropped_without_retry():
    outcome, notification = process_queued_message("{not json")
    assert outcome is Outcome.DROPPED_INVALID
    assert notification is None


def test_non_object_message_is_dropped():
    outcome, _ = process_queued_message("[1, 2, 3]")
    assert outcome is Outcome.DROPPED_INVALID


def test_message_missing_fields_is_dropped():
    outcome, _ = process_queued_message(json.dumps({"channel": "email"}))
    assert outcome is Outcome.DROPPED_INVALID


def test_invalid_notification_is_dropped_not_retried():
    bad = make_notification()
    object.__setattr__(bad, "recipient", "not-an-email")
    outcome, _ = process_queued_message(
        build_queue_message(bad),
        sender_factory=lambda _channel: FakeSender(),
    )
    assert outcome is Outcome.DROPPED_INVALID


def test_transient_failure_returns_retry_below_max_attempts():
    sender = FakeSender(fail_with=SenderTransientError("rate limited"))
    outcome, notification = process_queued_message(
        build_queue_message(make_notification()),
        sender_factory=lambda _channel: sender,
    )
    assert outcome is Outcome.RETRY
    assert notification is not None
    assert notification.attempts == 1
    assert sender.sent == []


def test_transient_failure_at_max_attempts_dead_letters(dead_letter_box):
    sender = FakeSender(fail_with=SenderTransientError("still down"))
    notification = make_notification(attempts=MAX_ATTEMPTS - 1)
    outcome, bumped = process_queued_message(
        build_queue_message(notification),
        sender_factory=lambda _channel: sender,
        dead_letter=dead_letter_box.append,
    )
    assert outcome is Outcome.DEAD_LETTERED
    assert bumped is not None and bumped.attempts == MAX_ATTEMPTS
    assert len(dead_letter_box) == 1
    assert json.loads(dead_letter_box[0])["id"] == notification.id


def test_permanent_failure_dead_letters_immediately(dead_letter_box):
    sender = FakeSender(fail_with=SenderPermanentError("bad address"))
    outcome, _ = process_queued_message(
        build_queue_message(make_notification()),
        sender_factory=lambda _channel: sender,
        dead_letter=dead_letter_box.append,
    )
    assert outcome is Outcome.DEAD_LETTERED
    assert len(dead_letter_box) == 1


def test_unexpected_sender_error_is_treated_as_transient():
    sender = FakeSender(fail_with=RuntimeError("boom"))
    outcome, _ = process_queued_message(
        build_queue_message(make_notification()),
        sender_factory=lambda _channel: sender,
    )
    assert outcome is Outcome.RETRY


def test_sender_is_selected_by_channel():
    seen: list[str] = []

    def factory(channel: str):
        seen.append(channel)
        return FakeSender()

    process_queued_message(
        build_queue_message(make_notification(channel="sms", recipient="+14165551234")),
        sender_factory=factory,
    )
    assert seen == ["sms"]


# --- queue trigger wrapper -------------------------------------------------

def test_queue_trigger_delivers_message(monkeypatch):
    sender = FakeSender()
    # process_queued_message resolves get_sender at call time, so patching
    # the processing module's reference redirects the trigger's sender.
    import aznotify.processing as processing

    monkeypatch.setattr(processing, "get_sender", lambda _channel: sender)
    function_app.queue_process(queue_message_for(make_notification()))
    assert len(sender.sent) == 1


def test_queue_trigger_raises_on_transient_failure(monkeypatch):
    import aznotify.processing as processing

    monkeypatch.setattr(
        processing,
        "get_sender",
        lambda _channel: FakeSender(fail_with=SenderTransientError("down")),
    )
    with pytest.raises(RuntimeError, match="retrying"):
        function_app.queue_process(queue_message_for(make_notification()))


def test_queue_trigger_drops_invalid_message_without_raising():
    function_app.queue_process(FakeQueueMessage("{nope"))
    # No exception: invalid messages must not be retried forever.
