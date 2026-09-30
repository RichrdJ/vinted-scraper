"""Notifier registry and dispatch.

RSS is intentionally not a push notifier: the feed is generated on demand by the web
UI from the ``items`` table, so enabling it only flips a flag.
"""
from typing import List

from logger import get_logger
from notifiers.base import Notification, Notifier
from notifiers.ntfy import NtfyNotifier
from notifiers.telegram import TelegramNotifier

logger = get_logger(__name__)

_ALL: List[Notifier] = [TelegramNotifier(), NtfyNotifier()]


def enabled_notifiers() -> List[Notifier]:
    return [n for n in _ALL if n.enabled()]


def dispatch(notification: Notification) -> None:
    """Send a notification to every enabled channel."""
    for notifier in _ALL:
        try:
            if notifier.enabled():
                notifier.send(notification)
        except Exception:
            logger.error("Notifier %s failed", notifier.name, exc_info=True)


def get_notifier(name: str) -> Notifier:
    for notifier in _ALL:
        if notifier.name == name:
            return notifier
    raise KeyError(name)


__all__ = ["Notification", "Notifier", "dispatch", "enabled_notifiers", "get_notifier"]
