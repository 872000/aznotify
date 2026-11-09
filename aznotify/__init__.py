"""aznotify package — Azure Functions serverless notification API."""

from .models import Notification, NotificationRequest, ValidationError
from .queue import NOTIFICATION_QUEUE_NAME, POISON_QUEUE_NAME
from .senders import ConsoleSender, NotificationSender, SendResult

__all__ = [
    "ConsoleSender",
    "Notification",
    "NotificationRequest",
    "NotificationSender",
    "NOTIFICATION_QUEUE_NAME",
    "POISON_QUEUE_NAME",
    "SendResult",
    "ValidationError",
]
