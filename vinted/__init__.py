"""Minimal Vinted API client used by vinted-scraper."""
from vinted.client import VintedClient, client
from vinted.item import Item
from vinted.requester import Requester, requester

__all__ = ["VintedClient", "client", "Item", "Requester", "requester"]
