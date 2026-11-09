"""Tests for payload validation (aznotify.models.validate_payload)."""

import pytest

from aznotify.models import ValidationError, validate_payload


def test_valid_email_payload():
    req = validate_payload(
        {"recipient": "parth@example.com", "channel": "email", "message": "Hi"}
    )
    assert req.recipient == "parth@example.com"
    assert req.channel == "email"
    assert req.message == "Hi"
    assert req.subject is None


def test_valid_sms_payload():
    req = validate_payload(
        {"recipient": "+14165551234", "channel": "sms", "message": "Hi"}
    )
    assert req.channel == "sms"


def test_valid_push_payload_with_subject():
    req = validate_payload(
        {
            "recipient": "device-token-abcdef1234",
            "channel": "push",
            "message": "Hi",
            "subject": "Greeting",
        }
    )
    assert req.subject == "Greeting"


def test_non_object_body_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(["not", "an", "object"])
    assert "must be a JSON object" in exc_info.value.errors[0]


def test_missing_recipient():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload({"channel": "email", "message": "Hi"})
    assert any("recipient" in e for e in exc_info.value.errors)


def test_missing_channel():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload({"recipient": "a@b.com", "message": "Hi"})
    assert any("channel" in e for e in exc_info.value.errors)


def test_unknown_channel():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(
            {"recipient": "a@b.com", "channel": "carrier-pigeon", "message": "Hi"}
        )
    assert any("email, sms, push" in e for e in exc_info.value.errors)


def test_missing_message():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload({"recipient": "a@b.com", "channel": "email"})
    assert any("message" in e for e in exc_info.value.errors)


def test_blank_message_rejected():
    with pytest.raises(ValidationError):
        validate_payload(
            {"recipient": "a@b.com", "channel": "email", "message": "   "}
        )


def test_bad_email_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(
            {"recipient": "not-an-email", "channel": "email", "message": "Hi"}
        )
    assert any("valid email" in e for e in exc_info.value.errors)


def test_bad_phone_rejected():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(
            {"recipient": "4165551234", "channel": "sms", "message": "Hi"}
        )
    assert any("E.164" in e for e in exc_info.value.errors)


def test_short_push_token_rejected():
    with pytest.raises(ValidationError):
        validate_payload(
            {"recipient": "abc", "channel": "push", "message": "Hi"}
        )


def test_message_too_long():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(
            {"recipient": "a@b.com", "channel": "email", "message": "x" * 1001}
        )
    assert any("1000" in e for e in exc_info.value.errors)


def test_subject_too_long():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload(
            {
                "recipient": "a@b.com",
                "channel": "email",
                "message": "Hi",
                "subject": "s" * 201,
            }
        )
    assert any("200" in e for e in exc_info.value.errors)


def test_multiple_problems_reported_at_once():
    with pytest.raises(ValidationError) as exc_info:
        validate_payload({"recipient": "", "channel": "smoke-signal"})
    assert len(exc_info.value.errors) >= 2


def test_whitespace_is_stripped():
    req = validate_payload(
        {
            "recipient": "  parth@example.com ",
            "channel": "email",
            "message": "  Hi there  ",
        }
    )
    assert req.recipient == "parth@example.com"
    assert req.message == "Hi there"


def test_extra_fields_are_ignored():
    req = validate_payload(
        {
            "recipient": "a@b.com",
            "channel": "email",
            "message": "Hi",
            "priority": "high",
        }
    )
    assert req.message == "Hi"
