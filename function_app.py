"""Azure Functions entry points for aznotify.

Two triggers:

- ``POST /api/notify`` (HTTP): validates a notification request and
  enqueues it on the ``notifications`` queue. Returns 202 Accepted.
- ``notifications`` queue trigger: delivers each queued notification
  through the pluggable sender (console by default).

All decision-making lives in the ``aznotify`` package so it can be tested
offline; these functions are thin adapters over the Azure SDK types.
The ``_enqueue`` / ``_dead_letter`` helpers are module-level functions so
tests can monkeypatch them instead of touching Azure Storage.
"""

from __future__ import annotations

import json
import logging
import os

import azure.functions as func

from aznotify.models import Notification, ValidationError, validate_payload
from aznotify.processing import Outcome, process_queued_message
from aznotify.queue import (
    NOTIFICATION_QUEUE_NAME,
    POISON_QUEUE_NAME,
    build_queue_message,
)

logger = logging.getLogger(__name__)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _queue_client(queue_name: str) -> "QueueClient":
    """Build a QueueClient from the Functions storage connection string."""
    # Imported lazily so the trigger module loads (and tests run) without
    # the storage SDK installed; only actual enqueue/dead-letter needs it.
    from azure.storage.queue import QueueClient

    connection_string = os.environ["AzureWebJobsStorage"]
    client = QueueClient.from_connection_string(connection_string, queue_name)
    try:
        client.create_queue()
    except Exception:  # noqa: BLE001 — queue probably already exists
        pass
    return client


def _enqueue(message: str) -> None:
    _queue_client(NOTIFICATION_QUEUE_NAME).send_message(message)


def _dead_letter(message: str) -> None:
    _queue_client(POISON_QUEUE_NAME).send_message(message)


@app.route(route="notify", methods=["POST"])
def http_notify(req: func.HttpRequest) -> func.HttpResponse:
    """Accept a notification request, validate it, enqueue it."""
    try:
        payload = json.loads(req.get_body().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON."}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        request = validate_payload(payload)
    except ValidationError as exc:
        return func.HttpResponse(
            json.dumps({"error": "Validation failed.", "details": exc.errors}),
            status_code=400,
            mimetype="application/json",
        )

    notification = Notification.new(request)
    try:
        _enqueue(build_queue_message(notification))
    except Exception:  # noqa: BLE001 — storage outage, bad connection string
        logger.exception("failed to enqueue notification %s", notification.id)
        return func.HttpResponse(
            json.dumps({"error": "Failed to enqueue notification."}),
            status_code=500,
            mimetype="application/json",
        )

    logger.info(
        "enqueued notification %s for %s via %s",
        notification.id,
        notification.recipient,
        notification.channel,
    )
    return func.HttpResponse(
        json.dumps(
            {
                "id": notification.id,
                "status": "queued",
                "queue": NOTIFICATION_QUEUE_NAME,
                "channel": notification.channel,
                "recipient": notification.recipient,
            }
        ),
        status_code=202,
        mimetype="application/json",
    )


@app.queue_trigger(
    arg_name="msg",
    queue_name=NOTIFICATION_QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
def queue_process(msg: func.QueueMessage) -> None:
    """Deliver one queued notification.

    Raises on transient failure so the Functions runtime redelivers the
    message (up to ``maxDequeueCount`` in host.json); after the final
    attempt the message is dead-lettered to the poison queue.
    """
    raw = msg.get_body()
    outcome, notification = process_queued_message(
        raw, dead_letter=_dead_letter
    )
    if outcome is Outcome.RETRY:
        raise RuntimeError(
            "Transient send failure for notification "
            f"{notification.id if notification else 'unknown'}; retrying."
        )
    if outcome is Outcome.DEAD_LETTERED:
        logger.error(
            "notification %s dead-lettered to %s",
            notification.id if notification else "unknown",
            POISON_QUEUE_NAME,
        )
    elif outcome is Outcome.DROPPED_INVALID:
        logger.warning("dropped invalid queue message without retrying")
