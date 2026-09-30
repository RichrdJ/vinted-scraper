"""Optional proxy support for the Vinted requester.

Proxies can be supplied as a ``;``-separated ``proxy_list`` parameter and/or a
``proxy_list_link`` URL returning one proxy per line. When ``check_proxies`` is on,
proxies are validated in parallel and only working ones are used. Results are cached
in-process and re-validated every few hours.
"""
import concurrent.futures
import random
import time
from typing import Dict, List, Optional

import requests

import db
from logger import get_logger

logger = get_logger(__name__)

_TEST_URL = "https://www.vinted.fr/"
_TEST_TIMEOUT = 3
_MAX_WORKERS = 10
_RECHECK_INTERVAL = 6 * 60 * 60  # 6 hours

_cache: Optional[List[str]] = None
_cache_time: float = 0.0


def to_dict(proxy: Optional[str]) -> Dict[str, str]:
    """Convert a proxy string to a requests proxies dict."""
    if not proxy:
        return {}
    if "://" not in proxy:
        proxy = "http://" + proxy
    return {"http": proxy, "https": proxy}


def _fetch_from_link(url: str) -> List[str]:
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
    except Exception:
        logger.warning("Could not fetch proxy list from %s", url)
    return []


def _check(proxy: str) -> bool:
    try:
        resp = requests.head(_TEST_URL, proxies=to_dict(proxy), timeout=_TEST_TIMEOUT)
        return resp.status_code < 500
    except Exception:
        return False


def _load() -> List[str]:
    all_proxies: List[str] = []

    raw = db.get_parameter("proxy_list") or ""
    all_proxies += [p.strip() for p in raw.split(";") if p.strip()]

    link = db.get_parameter("proxy_list_link") or ""
    if link:
        all_proxies += _fetch_from_link(link)

    if not all_proxies:
        return []

    if db.get_bool("check_proxies"):
        working: List[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            futures = {ex.submit(_check, p): p for p in all_proxies}
            for fut in concurrent.futures.as_completed(futures):
                if fut.result():
                    working.append(futures[fut])
        logger.info("Proxy check: %s/%s working", len(working), len(all_proxies))
        return working

    return all_proxies


def get_random_proxy() -> Optional[str]:
    global _cache, _cache_time
    now = time.time()
    if _cache is None or (now - _cache_time) > _RECHECK_INTERVAL:
        _cache = _load()
        _cache_time = now
    return random.choice(_cache) if _cache else None


def configure_proxy(session: requests.Session) -> bool:
    """Attach a random proxy to ``session``. Returns True if one was set."""
    proxy = get_random_proxy()
    if not proxy:
        session.proxies.clear()
        return False
    session.proxies.update(to_dict(proxy))
    return True


def invalidate_cache() -> None:
    global _cache
    _cache = None
