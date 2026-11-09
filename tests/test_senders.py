"""Tests for the sender interface (aznotify.senders)."""

import os

import pytest

from aznotify.senders import (
    ConsoleSender,
    FirebasePushSender,
    SmtpEmailSender,
    TwilioSmsSender,
    get_sender,
)
from tests.conftest import make_notification


def test_console_sender_records_and_returns_result(console_sender):
    notification = make_notification()
    result = console_sender.send(notification)
    assert result.channel == "email"
    assert result.recipient == "parth@example.com"
    assert result.provider == "console"
    assert result.message_id.startswith("console-")
    assert len(console_sender.sent) == 1


def test_console_sender_outboxes_are_independent():
    first, second = ConsoleSender(), ConsoleSender()
    first.send(make_notification())
    assert len(first.sent) == 1
    assert second.sent == []


def test_console_sender_message_ids_are_unique(console_sender):
    first = console_sender.send(make_notification())
    second = console_sender.send(make_notification())
    assert first.message_id != second.message_id


def test_smtp_stub_raises_not_implemented_with_guidance():
    with pytest.raises(NotImplementedError, match="SMTP_HOST"):
        SmtpEmailSender().send(make_notification())


def test_twilio_stub_raises_not_implemented_with_guidance():
    with pytest.raises(NotImplementedError, match="TWILIO_ACCOUNT_SID"):
        TwilioSmsSender().send(
            make_notification(channel="sms", recipient="+14165551234")
        )


def test_firebase_stub_raises_not_implemented_with_guidance():
    with pytest.raises(NotImplementedError, match="FIREBASE_CREDENTIALS"):
        FirebasePushSender().send(
            make_notification(channel="push", recipient="device-token-abcdef")
        )


def test_get_sender_defaults_to_console(monkeypatch):
    monkeypatch.delenv("AZNOTIFY_SENDER", raising=False)
    assert isinstance(get_sender(), ConsoleSender)


def test_get_sender_reads_env_var(monkeypatch):
    monkeypatch.setenv("AZNOTIFY_SENDER", "console")
    assert isinstance(get_sender(), ConsoleSender)


def test_get_sender_returns_stub_senders_by_name():
    assert isinstance(get_sender("smtp"), SmtpEmailSender)
    assert isinstance(get_sender("twilio"), TwilioSmsSender)
    assert isinstance(get_sender("firebase"), FirebasePushSender)


def test_get_sender_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown sender"):
        get_sender("pigeon")


def test_get_sender_name_is_case_insensitive():
    assert isinstance(get_sender("CONSOLE"), ConsoleSender)
