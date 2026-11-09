"""Tests for the HTTP trigger (function_app.http_notify).

The trigger's enqueue step is monkeypatched to an in-memory list, so no
Azure Storage is involved.
"""

import json

import function_app
from tests.conftest import make_http_request


def _enqueue_box(monkeypatch):
    box: list[str] = []
    monkeypatch.setattr(function_app, "_enqueue", box.append)
    return box


def test_good_payload_returns_202_and_enqueues(monkeypatch):
    box = _enqueue_box(monkeypatch)
    req = make_http_request(
        {"recipient": "parth@example.com", "channel": "email", "message": "Hello!"}
    )
    resp = function_app.http_notify(req)
    assert resp.status_code == 202
    body = json.loads(resp.get_body())
    assert body["status"] == "queued"
    assert body["queue"] == "notifications"
    assert body["channel"] == "email"
    assert body["id"]
    assert len(box) == 1
    queued = json.loads(box[0])
    assert queued["id"] == body["id"]
    assert queued["recipient"] == "parth@example.com"


def test_sms_payload_accepted(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(
        make_http_request(
            {"recipient": "+14165551234", "channel": "sms", "message": "Hi"}
        )
    )
    assert resp.status_code == 202


def test_invalid_json_returns_400(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(make_http_request("{not json"))
    assert resp.status_code == 400
    assert "valid JSON" in json.loads(resp.get_body())["error"]


def test_non_object_json_returns_400(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(make_http_request('["a", "b"]'))
    assert resp.status_code == 400
    assert "Validation failed" in json.loads(resp.get_body())["error"]


def test_missing_fields_returns_400_with_details(monkeypatch):
    box = _enqueue_box(monkeypatch)

    resp = function_app.http_notify(
        make_http_request({"channel": "email"})
    )
    assert resp.status_code == 400
    body = json.loads(resp.get_body())
    assert body["error"] == "Validation failed."
    assert len(body["details"]) >= 2
    assert box == []  # nothing enqueued on validation failure


def test_bad_channel_returns_400(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(
        make_http_request(
            {"recipient": "a@b.com", "channel": "fax", "message": "Hi"}
        )
    )
    assert resp.status_code == 400


def test_bad_email_returns_400(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(
        make_http_request(
            {"recipient": "nope", "channel": "email", "message": "Hi"}
        )
    )
    assert resp.status_code == 400


def test_message_too_long_returns_400(monkeypatch):
    _enqueue_box(monkeypatch)

    resp = function_app.http_notify(
        make_http_request(
            {"recipient": "a@b.com", "channel": "email", "message": "x" * 1001}
        )
    )
    assert resp.status_code == 400


def test_enqueue_failure_returns_500(monkeypatch):
    def boom(_message: str) -> None:
        raise RuntimeError("storage is down")

    monkeypatch.setattr(function_app, "_enqueue", boom)

    resp = function_app.http_notify(
        make_http_request(
            {"recipient": "a@b.com", "channel": "email", "message": "Hi"}
        )
    )
    assert resp.status_code == 500
    assert "Failed to enqueue" in json.loads(resp.get_body())["error"]
