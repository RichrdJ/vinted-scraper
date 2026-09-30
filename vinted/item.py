"""Parsed representation of a single Vinted listing (from catalog HTML)."""
from typing import Any, Dict, Optional


class Item:
    """Wraps one ``productItem`` object extracted from the catalog page.

    Vinted item ids are monotonically increasing, so ``id`` doubles as a recency
    key — novelty detection compares ids rather than timestamps (the search HTML
    does not expose a listing timestamp).
    """

    def __init__(self, data: Dict[str, Any], locale: str = "www.vinted.nl"):
        self.raw = data
        self.id = int(data["id"])
        self.title = (data.get("title") or "").strip()

        price = data.get("price") or {}
        self.price = price.get("amount")
        self.currency = price.get("currencyCode") or "EUR"

        box = data.get("itemBox") or {}
        self.brand = (box.get("firstLine") or "").strip()
        # secondLine is usually "<size> · <condition>".
        second = (box.get("secondLine") or "").strip()
        self.size = second.split("·")[0].strip() if second else None
        self.condition = second.split("·")[1].strip() if "·" in second else None

        # Prefer a higher-resolution photo when present, else the thumbnail.
        photos = data.get("photos") or []
        self.photo_url = (photos[0].get("url") if photos else None) or data.get("thumbnailUrl")

        rel = data.get("url") or ""
        self.url = rel if rel.startswith("http") else f"https://{locale}{rel}"

        user = data.get("user") or {}
        self.seller_id = user.get("id")
        self.seller_country = None  # not present in catalog HTML; fetched on demand

        self.is_promoted = bool(data.get("isPromoted"))

    @property
    def price_label(self) -> str:
        if self.price is None:
            return "?"
        return f"{self.price} {self.currency}"

    def __eq__(self, other):
        return isinstance(other, Item) and other.id == self.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"<Item {self.id} {self.title!r} {self.price_label}>"
