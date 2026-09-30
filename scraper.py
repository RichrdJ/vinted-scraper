"""Scraping engine: normalize searches, poll Vinted, dedupe and notify.

Novelty is decided by item id (Vinted ids increase monotonically): a search's
``last_item`` stores the highest id seen so far, and only items with a larger id are
considered new. The very first scrape of a query only records that high-water mark, so
you are not flooded with pre-existing listings.
"""
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import db
import notifiers
from logger import get_logger
from notifiers.base import Notification
from vinted import client
from vinted.item import Item

logger = get_logger(__name__)

_STRIP_PARAMS = ("time", "search_id", "disabled_personalization", "page", "order")


def normalize_query_url(url: str) -> str:
    """Return a canonical Vinted catalog URL (newest-first, volatile params removed)."""
    parsed = urlparse(url.strip())
    path_parts = parsed.path.strip("/").split("/")

    # Brand shortcut URL -> standard catalog filter.
    if len(path_parts) >= 2 and path_parts[0] == "brand":
        brand_id = path_parts[1].split("-")[0]
        parsed = parsed._replace(
            path="/catalog", query=urlencode({"brand_ids[]": [brand_id]}, doseq=True)
        )

    params = parse_qs(parsed.query, keep_blank_values=False)
    for key in _STRIP_PARAMS:
        params.pop(key, None)
    params["order"] = ["newest_first"]

    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def add_query(url: str, name: Optional[str] = None) -> Tuple[str, bool]:
    """Normalize and store a query. Returns (message, added?)."""
    if "vinted." not in urlparse(url).netloc:
        return "That doesn't look like a Vinted URL.", False
    normalized = normalize_query_url(url)
    if db.query_exists(normalized):
        return "Query already exists.", False
    db.add_query(normalized, name)
    logger.info("Added query: %s (%s)", normalized, name or "no name")
    return "Query added.", True


def _contains_banword(title: str, banwords_str: str) -> bool:
    banwords = [w.strip().lower() for w in (banwords_str or "").split("|||") if w.strip()]
    title_lower = title.lower()
    return any(w in title_lower for w in banwords)


def _seller_allowed(item: Item, allowlist, locale: str) -> bool:
    if not allowlist:
        return True
    country = item.seller_country or client.get_seller_country(item.seller_id, locale)
    if not country:
        return True  # unknown -> don't silently drop
    return country.upper() in allowlist


def _query_label(query_row) -> str:
    if query_row["name"]:
        return query_row["name"]
    params = parse_qs(urlparse(query_row["url"]).query)
    return params.get("search_text", ["(filters)"])[0]


def _notify(item: Item, query_row) -> None:
    db.add_item(
        item_id=item.id,
        query_id=query_row["id"],
        title=item.title,
        price=item.price,
        currency=item.currency,
        brand=item.brand,
        size=item.size,
        photo_url=item.photo_url,
        item_url=item.url,
        timestamp=item.id,  # id doubles as the recency/order key
    )
    notifiers.dispatch(
        Notification(
            title=item.title,
            price_label=item.price_label,
            brand=item.brand,
            size=item.size,
            url=item.url,
            photo_url=item.photo_url,
            query_name=_query_label(query_row),
        )
    )


def scrape_once() -> int:
    """Run one scrape cycle across all queries. Returns count of new items notified."""
    queries = db.get_queries()
    if not queries:
        return 0

    per_query = db.get_int("items_per_query", 20)
    allowlist = db.get_allowlist()
    banwords = db.get_parameter("banwords") or ""

    total_notified = 0
    for query in queries:
        locale = urlparse(query["url"]).netloc or "www.vinted.nl"
        last_id = query["last_item"]
        first_scrape = last_id is None

        try:
            items = client.search(query["url"], per_page=per_query)
        except Exception:
            logger.error("Scrape failed for %s", query["url"], exc_info=True)
            continue

        if not items:
            continue

        max_id = max(it.id for it in items)

        if first_scrape:
            # Seed the high-water mark only; do not notify pre-existing listings.
            db.update_last_timestamp(query["id"], max_id)
            logger.info("Seeded '%s' at id %s (%s items, no notify)",
                        _query_label(query), max_id, len(items))
            continue

        # Only genuinely new ids, oldest first for chronological delivery.
        fresh = sorted((it for it in items if it.id > last_id), key=lambda it: it.id)
        count = 0
        for item in fresh:
            if db.item_exists(item.id):
                continue
            if _contains_banword(item.title, banwords):
                continue
            if not _seller_allowed(item, allowlist, locale):
                continue
            _notify(item, query)
            count += 1

        # Advance the high-water mark past everything seen this cycle.
        db.update_last_timestamp(query["id"], max_id)

        total_notified += count
        logger.info("'%s': %s new item(s)", _query_label(query), count)

    return total_notified
