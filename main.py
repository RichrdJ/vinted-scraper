"""vinted-scraper entry point.

Wires together the pieces and runs them in one process:

  * a background scheduler that polls Vinted every ``query_refresh_delay`` seconds
  * an optional Telegram command bot (daemon thread)
  * the Flask web UI (main thread, blocking)

Notifications (Telegram push + ntfy) are sent inline from the scrape job.
"""
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

import config
import db
import scraper
from logger import get_logger

logger = get_logger(__name__)

_SCRAPE_JOB_ID = "scrape"
_current_delay = None


def _scrape_job():
    try:
        count = scraper.scrape_once()
        if count:
            logger.info("Notified %s new item(s)", count)
    except Exception:
        logger.error("Scrape cycle crashed", exc_info=True)


def _watch_refresh_delay(scheduler: BackgroundScheduler):
    """Reschedule the scrape job when the refresh delay is changed in the UI."""
    global _current_delay
    new_delay = db.get_int("query_refresh_delay", 60)
    if new_delay != _current_delay and new_delay >= 10:
        logger.info("Refresh delay changed: %ss -> %ss", _current_delay, new_delay)
        _current_delay = new_delay
        scheduler.reschedule_job(_SCRAPE_JOB_ID, trigger="interval", seconds=new_delay)


def _maybe_start_telegram_bot():
    if db.get_bool("telegram_enabled") and db.get_parameter("telegram_token"):
        import bot
        thread = threading.Thread(target=bot.run_bot, name="telegram-bot", daemon=True)
        thread.start()
    else:
        logger.info("Telegram command bot disabled (enable it and restart to use commands)")


def main():
    global _current_delay

    db.init_db()
    config.seed_from_env()

    _current_delay = db.get_int("query_refresh_delay", 60)

    scheduler = BackgroundScheduler(daemon=True)
    # Fire the first scrape shortly after boot, then every _current_delay seconds.
    scheduler.add_job(
        _scrape_job, "interval", seconds=_current_delay, id=_SCRAPE_JOB_ID,
        next_run_time=None, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _watch_refresh_delay, "interval", seconds=10, args=[scheduler], id="watch-delay",
    )
    scheduler.start()
    # Kick off an immediate first cycle without waiting a full interval.
    threading.Thread(target=_scrape_job, name="initial-scrape", daemon=True).start()

    _maybe_start_telegram_bot()

    logger.info("vinted-scraper started (refresh every %ss)", _current_delay)

    # Web UI blocks the main thread.
    from webui.app import run_web
    try:
        run_web()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down")
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
