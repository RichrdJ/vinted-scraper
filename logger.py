"""Central logging configuration.

Logs go to stderr and to a rotating file under ``data/vinted-scraper.log`` so the
web UI can tail them.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_LOG_FILE = os.path.join(_LOG_DIR, "vinted-scraper.log")
_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(_LEVEL)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet down noisy third-party loggers.
    for noisy in ("httpx", "apscheduler", "werkzeug", "urllib3", "telegram"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name``."""
    _configure_root()
    return logging.getLogger(name)


def get_log_path() -> str:
    return _LOG_FILE
