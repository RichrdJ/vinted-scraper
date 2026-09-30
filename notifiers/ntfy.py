"""ntfy.sh push notifications (https://ntfy.sh).

Publishes to ``{server}/{topic}`` with a click action that opens the listing and,
when available, the photo as an attachment/preview.
"""
import requests

import db
from logger import get_logger
from notifiers.base import Notification, Notifier

logger = get_logger(__name__)


class NtfyNotifier(Notifier):
    name = "ntfy"

    def enabled(self) -> bool:
        return db.get_bool("ntfy_enabled") and bool(db.get_parameter("ntfy_topic"))

    def send(self, n: Notification) -> None:
        server = (db.get_parameter("ntfy_server") or "https://ntfy.sh").rstrip("/")
        topic = db.get_parameter("ntfy_topic")
        token = db.get_parameter("ntfy_token")
        priority = db.get_parameter("ntfy_priority") or "default"

        # HTTP headers must be latin-1 encodable, so the (possibly non-latin) item
        # title goes in the UTF-8 body; the header title stays ASCII-safe.
        body_lines = [n.title, n.price_label]
        if n.brand:
            body_lines.append(n.brand)
        if n.size:
            body_lines.append(f"Size {n.size}")
        body_lines.append(f"Search: {n.query_name}")
        body = "\n".join(body_lines)

        def _ascii(text: str) -> str:
            cleaned = " ".join(text.encode("ascii", "ignore").decode("ascii").split())
            return cleaned or "New Vinted item"

        headers = {
            "Title": _ascii(f"New: {n.title}")[:200],
            "Priority": priority,
            "Tags": "shopping_bags",
            "Click": n.url,
            "Actions": f"view, Open on Vinted, {n.url}",
        }
        if n.photo_url:
            headers["Attach"] = n.photo_url
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = requests.post(
                f"{server}/{topic}",
                data=body.encode("utf-8"),
                headers=headers,
                timeout=20,
            )
            if resp.status_code >= 300:
                logger.error("ntfy send failed (%s): %.200s", resp.status_code, resp.text)
        except Exception:
            logger.error("ntfy send raised", exc_info=True)
