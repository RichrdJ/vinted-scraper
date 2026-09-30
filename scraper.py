"""Scraping engine: normalize searches, poll Vinted, dedupe and notify.

Novelty is decided by item id (Vinted ids increase monotonically): a search's
``last_item`` stores the highest id seen so far, and only items with a larger id are
considered new. The very first scrape of a query only records that high-water mark, so
you are not flooded with pre-existing listings.
"""
import random
import threading
import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import db
import notifiers
from logger import get_logger
from notifiers.base import Notification
from vinted import VintedFetchError, client
from vinted.item import Item

logger = get_logger(__name__)

_STRIP_PARAMS = ("time", "search_id", "disabled_personalization", "page", "order")

# Only one scan (scheduled or manual) may run at a time, so the same item can never
# be notified twice by overlapping scans.
_scan_lock = threading.Lock()

# Minimum seconds between two scans of the same search when triggered by hand.
MANUAL_SCAN_COOLDOWN = 60

# Pause between individual searches within one cycle, to avoid request bursts.
_QUERY_PAUSE_SECONDS = (3.0, 8.0)

# Vinted domains selectable when creating a search from a keyword.
DOMAINS = {
    "www.vinted.nl": "Nederland",
    "www.vinted.be": "België",
    "www.vinted.de": "Duitsland",
    "www.vinted.fr": "Frankrijk",
    "www.vinted.es": "Spanje",
    "www.vinted.it": "Italië",
    "www.vinted.co.uk": "Verenigd Koninkrijk",
}


def build_search_url(
    keyword: str,
    domain: str = "www.vinted.nl",
    price_from: Optional[str] = None,
    price_to: Optional[str] = None,
) -> str:
    """Build a Vinted catalog URL from a keyword and optional price range."""
    if domain not in DOMAINS:
        domain = "www.vinted.nl"
    params = {"search_text": keyword.strip()}
    currency = "GBP" if domain.endswith(".co.uk") else "EUR"
    for key, value in (("price_from", price_from), ("price_to", price_to)):
        if value not in (None, ""):
            params[key] = str(value).strip().replace(",", ".")
            params["currency"] = currency
    return f"https://{domain}/catalog?{urlencode(params)}"


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


def update_search(query_id: int, url: str, name: Optional[str]) -> Tuple[str, bool]:
    """Edit a search. Changing the URL restarts it, so no burst of old listings."""
    query = db.get_query(query_id)
    if query is None:
        return "Search not found.", False
    if "vinted." not in urlparse(url).netloc:
        return "That doesn't look like a Vinted URL.", False
    normalized = normalize_query_url(url)
    url_changed = normalized != query["url"]
    if not db.update_query(query_id, normalized, name, reset_progress=url_changed):
        return "Another search already uses that URL.", False
    logger.info("Updated query %s: %s (%s)", query_id, normalized, name or "no name")
    if url_changed:
        return "Search updated. The new URL starts fresh: existing listings won't be notified.", True
    return "Search updated.", True


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


def _load_settings() -> dict:
    return {
        "per_query": db.get_int("items_per_query", 20),
        "allowlist": db.get_allowlist(),
        "banwords": db.get_parameter("banwords") or "",
    }


def _scan_query(query, settings: dict) -> int:
    """Scan one search, store + notify new items. Returns the number notified.

    The outcome is recorded on the query (``last_scan_at`` / ``last_scan_result``)
    so the web UI can show when it last ran and whether it worked.
    """
    label = _query_label(query)
    locale = urlparse(query["url"]).netloc or "www.vinted.nl"
    last_id = query["last_item"]

    try:
        items = client.search(query["url"], per_page=settings["per_query"])
    except VintedFetchError as exc:
        db.set_scan_result(query["id"], f"Failed: {exc}")
        return 0
    except Exception:
        logger.error("Scrape failed for %s", query["url"], exc_info=True)
        db.set_scan_result(query["id"], "Failed: unexpected error (see Logs)")
        return 0

    if not items:
        db.set_scan_result(query["id"], "No listings found")
        logger.info("'%s': no listings found", label)
        return 0

    max_id = max(it.id for it in items)

    if last_id is None:
        # First scan: seed the high-water mark only, don't notify existing listings.
        db.update_last_timestamp(query["id"], max_id)
        db.set_scan_result(query["id"], f"Started watching ({len(items)} existing listings)")
        logger.info("Seeded '%s' at id %s (%s items, no notify)", label, max_id, len(items))
        return 0

    # Only genuinely new ids, oldest first for chronological delivery.
    fresh = sorted((it for it in items if it.id > last_id), key=lambda it: it.id)
    count = 0
    for item in fresh:
        if db.item_exists(item.id):
            continue
        if _contains_banword(item.title, settings["banwords"]):
            continue
        if not _seller_allowed(item, settings["allowlist"], locale):
            continue
        _notify(item, query)
        count += 1

    # Advance the high-water mark past everything seen this scan.
    db.update_last_timestamp(query["id"], max_id)
    db.set_scan_result(query["id"], f"{count} new item{'' if count == 1 else 's'}")
    logger.info("'%s': %s new item(s)", label, count)
    return count


def scrape_once() -> int:
    """Run one scheduled cycle across all queries. Returns count of new items notified."""
    with _scan_lock:
        queries = db.get_queries()
        settings = _load_settings()
        total = 0
        for index, query in enumerate(queries):
            if index:
                time.sleep(random.uniform(*_QUERY_PAUSE_SECONDS))
            total += _scan_query(query, settings)
        return total


def scan_now(query_id: int) -> Tuple[bool, str]:
    """Manually scan one search right away. Returns (ok, message).

    Refused while another scan is running, or when this search was scanned less
    than ``MANUAL_SCAN_COOLDOWN`` seconds ago (to stay under Vinted's radar).
    """
    query = db.get_query(query_id)
    if query is None:
        return False, "Search not found."
    if query["last_scan_at"]:
        wait = MANUAL_SCAN_COOLDOWN - (int(time.time()) - query["last_scan_at"])
        if wait > 0:
            return False, f"'{_query_label(query)}' was scanned just now; try again in {wait}s."
    if not _scan_lock.acquire(blocking=False):
        return False, "A scan is already running, try again in a moment."
    try:
        _scan_query(query, _load_settings())
    finally:
        _scan_lock.release()
    result = db.get_query(query_id)["last_scan_result"]
    return True, f"Scanned '{_query_label(query)}': {result}."


def scan_all_async() -> Tuple[bool, str]:
    """Start a full scan of every search in the background. Returns (ok, message)."""
    if _scan_lock.locked():
        return False, "A scan is already running."
    threading.Thread(target=scrape_once, name="manual-scan-all", daemon=True).start()
    return True, "Scanning all searches in the background. Refresh this page in a minute."


def is_scanning() -> bool:
    return _scan_lock.locked()
