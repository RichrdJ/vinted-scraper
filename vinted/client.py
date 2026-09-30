"""High-level Vinted search client.

Fetches a catalog page as HTML and extracts listings from the embedded Next.js RSC
payload (``self.__next_f.push([1,"..."])`` chunks), newest first.
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

from logger import get_logger
from vinted.item import Item
from vinted.requester import requester

logger = get_logger(__name__)

_RSC_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_PRODUCT_KEY = '"productItem":'

# Map Vinted locale -> a plausible Accept-Language, improves relevance/consistency.
_LANG = {
    "www.vinted.nl": "nl-NL,nl;q=0.9,en;q=0.8",
    "www.vinted.be": "nl-BE,nl;q=0.9,fr;q=0.8",
    "www.vinted.de": "de-DE,de;q=0.9,en;q=0.8",
    "www.vinted.fr": "fr-FR,fr;q=0.9,en;q=0.8",
    "www.vinted.co.uk": "en-GB,en;q=0.9",
    "www.vinted.com": "en-US,en;q=0.9",
}


def _decode_payload(html: str) -> str:
    chunks = _RSC_CHUNK.findall(html)
    if not chunks:
        return ""
    try:
        # Concatenate the raw JS-escaped chunks and decode as one JSON string so
        # \uXXXX / \" / UTF-8 escapes are handled correctly.
        return json.loads('"' + "".join(chunks) + '"')
    except json.JSONDecodeError:
        # Fall back to per-chunk decoding, skipping any malformed piece.
        parts = []
        for c in chunks:
            try:
                parts.append(json.loads('"' + c + '"'))
            except json.JSONDecodeError:
                continue
        return "".join(parts)


def _balanced_object(text: str, brace_start: int) -> Optional[str]:
    depth = 0
    for j in range(brace_start, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start:j + 1]
    return None


class VintedClient:
    def search(self, url: str, per_page: int = 20) -> List[Item]:
        """Return up to ``per_page`` listings for a Vinted catalog ``url``."""
        locale = urlparse(url).netloc or "www.vinted.nl"
        resp = requester.get(url, accept_language=_LANG.get(locale, "en-US,en;q=0.9"))

        if resp is None or resp.status_code != 200:
            status = resp.status_code if resp is not None else "no response"
            logger.error("Catalog fetch failed for %s (status: %s)", url, status)
            return []

        payload = _decode_payload(resp.text)
        if not payload:
            logger.error("No RSC data found in catalog page for %s", url)
            return []

        items: List[Item] = []
        seen = set()
        pos = 0
        while len(items) < per_page:
            i = payload.find(_PRODUCT_KEY, pos)
            if i < 0:
                break
            brace = payload.find("{", i + len(_PRODUCT_KEY))
            pos = i + len(_PRODUCT_KEY)
            obj_str = _balanced_object(payload, brace) if brace >= 0 else None
            if not obj_str:
                continue
            try:
                data = json.loads(obj_str)
            except json.JSONDecodeError:
                continue
            item_id = data.get("id")
            if item_id in seen or data.get("isPromoted"):
                continue
            seen.add(item_id)
            try:
                items.append(Item(data, locale))
            except (KeyError, ValueError, TypeError):
                continue

        logger.debug("Parsed %s items from %s", len(items), url)
        return items

    def get_seller_country(self, seller_id: int, locale: str = "www.vinted.fr") -> Optional[str]:
        """Best-effort seller country ISO code via the (unshielded) users endpoint."""
        if not seller_id:
            return None
        api = f"https://{locale}/api/v2/users/{seller_id}?localize=false"
        resp = requester.get(api)
        if resp is None or resp.status_code != 200:
            return None
        try:
            return resp.json().get("user", {}).get("country_iso_code")
        except Exception:
            return None


client = VintedClient()
