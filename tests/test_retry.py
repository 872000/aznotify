"""Tests for queue serialisation and retry / dead-letter rules."""

import json

import pytest

from aznotify.models import Notification
from aznotify.queue import (
    MAX_ATTEMPTS,
    build_queue_message,
    parse_queue_message,
    should_retry,
    with_attempts,
)
from tests.conftest import make_notification


def test_build_and_parse_round_trip():
    original = make_notification(subject="Hello")
    parsed = parse_queue_message(build_queue_message(original))
    assert parsed.id == original.id
    assert parsed.recipient == original.recipient
    assert parsed.channel == original.channel
    assert parsed.message == original.message
    assert parsed.subject == "Hello"
    assert parsed.attempts == 0


def test_parse_accepts_bytes():
    original = make_notification()
    parsed = parse_queue_message(build_queue_message(original).encode("utf-8"))
    assert parsed.id == original.id


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_queue_message("{broken")


def test_parse_non_object_raises():
    with pytest.raises(ValueError, match="JSON object"):
        parse_queue_message("[1, 2]")


def test_parse_missing_fields_raises():
    with pytest.raises(ValueError, match="missing required fields"):
        parse_queue_message(json.dumps({"channel": "email"}))


def test_notification_from_dict_defaults_attempts_to_zero():
    notification = Notification.from_dict(
        {
            "id": "abc",
            "recipient": "a@b.com",
            "channel": "email",
            "message": "Hi",
        }
    )
    assert notification.attempts == 0


def test_should_retry_below_max():
    assert should_retry(0) is True
    assert should_retry(MAX_ATTEMPTS - 1) is True


def test_should_not_retry_at_or_above_max():
    assert should_retry(MAX_ATTEMPTS) is False
    assert should_retry(MAX_ATTEMPTS + 10) is False


def test_with_attempts_returns_updated_copy():
    original = make_notification(attempts=1)
    bumped = with_attempts(original, 3)
    assert bumped.attempts == 3
    assert original.attempts == 1  # original untouched
    assert bumped.id == original.id


def test_max_attempts_is_five():
    assert MAX_ATTEMPTS == 5
