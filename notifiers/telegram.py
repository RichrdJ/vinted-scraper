"""Telegram delivery via the Bot HTTP API.

Sending notifications does not need the polling bot to be running — it is a plain
HTTPS call to ``sendPhoto`` / ``sendMessage``. The interactive command bot (add/remove
queries from a chat) lives separately in ``bot.py``.
"""
import html

import requests

import db
from logger import get_logger
from notifiers.base import Notification, Notifier

logger = get_logger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier(Notifier):
    name = "telegram"

    def enabled(self) -> bool:
        return (
            db.get_bool("telegram_enabled")
            and bool(db.get_parameter("telegram_token"))
            and bool(db.get_parameter("telegram_chat_id"))
        )

    def _caption(self, n: Notification) -> str:
        parts = [f"🆕 <b>{html.escape(n.title)}</b>", f"💶 {html.escape(n.price_label)}"]
        if n.brand:
            parts.append(f"🏷️ {html.escape(n.brand)}")
        if n.size:
            parts.append(f"📏 {html.escape(n.size)}")
        parts.append(f"🔎 <i>{html.escape(n.query_name)}</i>")
        return "\n".join(parts)

    def send(self, n: Notification) -> None:
        token = db.get_parameter("telegram_token")
        chat_id = db.get_parameter("telegram_chat_id")
        caption = self._caption(n)
        keyboard = {
            "inline_keyboard": [[{"text": "🛒 Open on Vinted", "url": n.url}]]
        }

        try:
            if n.photo_url:
                resp = requests.post(
                    API.format(token=token, method="sendPhoto"),
                    json={
                        "chat_id": chat_id,
                        "photo": n.photo_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard,
                    },
                    timeout=20,
                )
            else:
                resp = requests.post(
                    API.format(token=token, method="sendMessage"),
                    json={
                        "chat_id": chat_id,
                        "text": caption + "\n" + n.url,
                        "parse_mode": "HTML",
                        "reply_markup": keyboard,
                        "disable_web_page_preview": False,
                    },
                    timeout=20,
                )
            if resp.status_code != 200:
                logger.error("Telegram send failed (%s): %.200s", resp.status_code, resp.text)
        except Exception:
            logger.error("Telegram send raised", exc_info=True)
