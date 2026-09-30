"""HTTP layer for Vinted.

Vinted's catalog is served by Next.js behind Cloudflare + DataDome bot protection.
The raw ``/api/v2/catalog/items`` JSON endpoint is blocked for non-browser clients, so
we instead fetch the normal catalog *HTML page* (which renders fine) using
``curl_cffi`` with a real Chrome TLS/JA3 fingerprint, and parse the embedded data.

A few JSON endpoints (e.g. ``/api/v2/users/{id}``) are not shielded and still work with
the same impersonated client; those are used for optional seller-country lookups.
"""
import random

from curl_cffi import requests as cffi

import proxies
from logger import get_logger

logger = get_logger(__name__)

# Chrome versions curl_cffi can impersonate; rotated on session reset.
_IMPERSONATE = ["chrome", "chrome110", "chrome116", "chrome120", "chrome124"]


class Requester:
    MAX_RETRIES = 3

    def __init__(self):
        self._impersonate = "chrome"
        self.session = self._new_session()

    def _new_session(self):
        self._impersonate = random.choice(_IMPERSONATE)
        return cffi.Session(impersonate=self._impersonate)

    def reset(self) -> None:
        self.session = self._new_session()
        logger.debug("Requester session reset (impersonate=%s)", self._impersonate)

    def _proxy_kwargs(self) -> dict:
        proxy = proxies.get_random_proxy()
        return {"proxies": proxies.to_dict(proxy)} if proxy else {}

    def get(self, url: str, params=None, accept_language: str = "en-US,en;q=0.9"):
        """GET ``url`` with browser impersonation and retries. Returns the response."""
        last = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers={"Accept-Language": accept_language},
                    timeout=25,
                    **self._proxy_kwargs(),
                )
            except Exception:
                logger.warning("Request error for %s (attempt %s)", url, attempt, exc_info=True)
                self.reset()
                continue

            last = resp
            if resp.status_code == 200:
                return resp

            logger.debug("HTTP %s for %s (attempt %s)", resp.status_code, url, attempt)
            if attempt < self.MAX_RETRIES:
                self.reset()
        return last


requester = Requester()
