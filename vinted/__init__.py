"""Minimal Vinted API client used by vinted-scraper."""
from vinted.client import VintedClient, VintedFetchError, client
from vinted.item import Item
from vinted.requester import Requester, requester

__all__ = ["VintedClient", "VintedFetchError", "client", "Item", "Requester", "requester"]
