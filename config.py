"""Bootstrap configuration from environment / .env into the parameters table.

Environment variables are only used to *seed* a parameter when its stored value is
still empty, so edits made later in the web UI are never clobbered on restart. To
force a value from the environment on every boot, prefix it with ``FORCE_`` (e.g.
``FORCE_TELEGRAM_TOKEN``).
"""
import os

import db
from logger import get_logger

logger = get_logger(__name__)

# Web UI network settings are process-level (not runtime editable), so they are read
# straight from the environment here.
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "8344"))
WEB_USERNAME = os.environ.get("WEB_USERNAME", "")  # optional basic-auth
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")

# env var -> parameter key
_ENV_TO_PARAM = {
    "TELEGRAM_ENABLED": "telegram_enabled",
    "TELEGRAM_TOKEN": "telegram_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "NTFY_ENABLED": "ntfy_enabled",
    "NTFY_SERVER": "ntfy_server",
    "NTFY_TOPIC": "ntfy_topic",
    "NTFY_TOKEN": "ntfy_token",
    "NTFY_PRIORITY": "ntfy_priority",
    "RSS_ENABLED": "rss_enabled",
    "RSS_MAX_ITEMS": "rss_max_items",
    "ITEMS_PER_QUERY": "items_per_query",
    "QUERY_REFRESH_DELAY": "query_refresh_delay",
    "BANWORDS": "banwords",
    "PROXY_LIST": "proxy_list",
    "PROXY_LIST_LINK": "proxy_list_link",
    "CHECK_PROXIES": "check_proxies",
    "GITHUB_URL": "github_url",
}


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def seed_from_env() -> None:
    """Seed parameters from the environment. Call once, after ``db.init_db()``."""
    _load_dotenv()
    for env_key, param_key in _ENV_TO_PARAM.items():
        forced = os.environ.get("FORCE_" + env_key)
        if forced is not None:
            db.set_parameter(param_key, forced)
            logger.info("Parameter %s forced from environment", param_key)
            continue

        value = os.environ.get(env_key)
        if value is None:
            continue
        current = (db.get_parameter(param_key) or "").strip()
        if current == "":
            db.set_parameter(param_key, value)
            logger.info("Parameter %s seeded from environment", param_key)
