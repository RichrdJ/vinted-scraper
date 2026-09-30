"""vinted-scraper entry point.

Wires together the pieces and runs them in one process:

  * a background scheduler that polls Vinted every ``refresh_minutes`` minutes
    (minimum 5, with random jitter so requests don't look machine-timed)
  * an optional Telegram command bot (daemon thread)
  * the Flask web UI (main thread, blocking)

Notifications (Telegram push + ntfy) are sent inline from the scrape job.
"""
import threading

from apscheduler.schedulers.background import BackgroundScheduler

import config
import db
import scraper
from logger import get_logger

logger = get_logger(__name__)

_SCRAPE_JOB_ID = "scrape"
_JITTER_SECONDS = 45
_current_minutes = None


def _scrape_job():
    try:
        count = scraper.scrape_once()
        if count:
            logger.info("Notified %s new item(s)", count)
    except Exception:
        logger.error("Scrape cycle crashed", exc_info=True)


def _watch_refresh_interval(scheduler: BackgroundScheduler):
    """Reschedule the scrape job when the interval is changed in the UI."""
    global _current_minutes
    minutes = db.get_refresh_minutes()
    if minutes != _current_minutes:
        logger.info("Refresh interval changed: %s -> %s min", _current_minutes, minutes)
        _current_minutes = minutes
        scheduler.reschedule_job(
            _SCRAPE_JOB_ID, trigger="interval", minutes=minutes, jitter=_JITTER_SECONDS
        )


def _maybe_start_telegram_bot():
    if db.get_bool("telegram_enabled") and db.get_parameter("telegram_token"):
        import bot
        thread = threading.Thread(target=bot.run_bot, name="telegram-bot", daemon=True)
        thread.start()
    else:
        logger.info("Telegram command bot disabled (enable it and restart to use commands)")


def main():
    global _current_minutes

    db.init_db()
    config.seed_from_env()

    _current_minutes = db.get_refresh_minutes()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _scrape_job, "interval", minutes=_current_minutes, jitter=_JITTER_SECONDS,
        id=_SCRAPE_JOB_ID, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _watch_refresh_interval, "interval", seconds=15, args=[scheduler], id="watch-interval",
    )
    scheduler.start()
    # Kick off an immediate first cycle without waiting a full interval.
    threading.Thread(target=_scrape_job, name="initial-scrape", daemon=True).start()

    _maybe_start_telegram_bot()

    logger.info("vinted-scraper %s started (refresh every %s min)", config.VERSION, _current_minutes)

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
