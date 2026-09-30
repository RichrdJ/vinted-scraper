"""Shared notification model and base class."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Notification:
    """A single new-listing event, ready to be delivered to any channel."""
    title: str
    price_label: str
    brand: str
    size: Optional[str]
    url: str
    photo_url: Optional[str]
    query_name: str

    def as_plaintext(self) -> str:
        lines = [f"🆕 {self.title}", f"💶 {self.price_label}"]
        if self.brand:
            lines.append(f"🏷️ {self.brand}")
        if self.size:
            lines.append(f"📏 {self.size}")
        lines.append(f"🔎 {self.query_name}")
        lines.append(self.url)
        return "\n".join(lines)


class Notifier:
    """Base class for a delivery channel."""

    name = "base"

    def enabled(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def send(self, notification: Notification) -> None:  # pragma: no cover
        raise NotImplementedError
