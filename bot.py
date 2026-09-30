"""Optional interactive Telegram bot.

Lets you manage searches from a chat with commands like ``/add`` and ``/queries``.
Runs in its own thread with a dedicated asyncio loop. Only the configured chat id is
allowed to issue commands. Sending notifications does not depend on this bot.
"""
import asyncio
from typing import Optional

import db
import scraper
from logger import get_logger

logger = get_logger(__name__)

HELP = (
    "🤖 *vinted-scraper*\n\n"
    "/add <search term> — add a search on vinted.nl\n"
    "/add <vinted-url> [name] — add a search with filters\n"
    "/queries — list searches\n"
    "/remove <number|all> — remove a search\n"
    "/allow <XX> — add country to seller allowlist\n"
    "/disallow <XX> — remove country from allowlist\n"
    "/allowlist — show allowlist\n"
    "/status — show current status\n"
    "/help — this message"
)


def _authorized(update) -> bool:
    allowed = str(db.get_parameter("telegram_chat_id") or "")
    return allowed != "" and str(update.effective_chat.id) == allowed


async def _guard(update) -> bool:
    if not _authorized(update):
        await update.message.reply_text("Not authorized for this chat.")
        return False
    return True


async def cmd_start(update, context):
    if not await _guard(update):
        return
    await update.message.reply_text(HELP, parse_mode="Markdown")


async def cmd_add(update, context):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /add <search term> or /add <vinted-url> [name]")
        return
    if context.args[0].startswith("http"):
        url = context.args[0]
        name = " ".join(context.args[1:]) or None
    else:
        keyword = " ".join(context.args)
        url = scraper.build_search_url(keyword)
        name = keyword
    message, _ = scraper.add_query(url, name)
    await update.message.reply_text(message)


async def cmd_queries(update, context):
    if not await _guard(update):
        return
    rows = db.get_queries()
    if not rows:
        await update.message.reply_text("No searches yet. Add one with /add.")
        return
    lines = []
    for i, row in enumerate(rows, 1):
        label = row["name"] or row["url"]
        lines.append(f"{i}. {label}")
    await update.message.reply_text("\n".join(lines))


async def cmd_remove(update, context):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <number|all>")
        return
    arg = context.args[0].lower()
    if arg == "all":
        db.remove_all_queries()
        await update.message.reply_text("All searches removed.")
        return
    if not arg.isdigit():
        await update.message.reply_text("Give a query number (see /queries) or 'all'.")
        return
    rows = db.get_queries()
    idx = int(arg) - 1
    if 0 <= idx < len(rows):
        db.remove_query(rows[idx]["id"])
        await update.message.reply_text("Search removed.")
    else:
        await update.message.reply_text("No search with that number.")


async def cmd_allow(update, context):
    if not await _guard(update):
        return
    if not context.args or len(context.args[0]) != 2:
        await update.message.reply_text("Usage: /allow <2-letter country code>")
        return
    db.add_to_allowlist(context.args[0])
    await update.message.reply_text(f"Allowlist: {', '.join(db.get_allowlist()) or '(empty)'}")


async def cmd_disallow(update, context):
    if not await _guard(update):
        return
    if not context.args or len(context.args[0]) != 2:
        await update.message.reply_text("Usage: /disallow <2-letter country code>")
        return
    db.remove_from_allowlist(context.args[0])
    await update.message.reply_text(f"Allowlist: {', '.join(db.get_allowlist()) or '(empty)'}")


async def cmd_allowlist(update, context):
    if not await _guard(update):
        return
    countries = db.get_allowlist()
    await update.message.reply_text(
        "Allowlist: " + (", ".join(countries) if countries else "(empty = all countries)")
    )


async def cmd_status(update, context):
    if not await _guard(update):
        return
    stats = db.get_stats()
    await update.message.reply_text(
        f"Searches: {stats['total_queries']}\n"
        f"Items found: {stats['total_items']}\n"
        f"Items/day: {stats['items_per_day']}\n"
        f"Refresh: every {db.get_refresh_minutes()} min"
    )


def build_application(token: str):
    from telegram.ext import Application, CommandHandler

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("queries", cmd_queries))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("disallow", cmd_disallow))
    app.add_handler(CommandHandler("allowlist", cmd_allowlist))
    app.add_handler(CommandHandler("status", cmd_status))
    return app


def run_bot(token: Optional[str] = None) -> None:
    """Blocking; intended to be the target of a daemon thread."""
    token = token or db.get_parameter("telegram_token")
    if not token:
        logger.warning("Telegram bot not started: no token configured")
        return

    # A dedicated event loop is required because we are not on the main thread.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = build_application(token)
    logger.info("Telegram command bot started")
    try:
        # stop_signals=None: signal handlers can only be installed on the main thread.
        app.run_polling(stop_signals=None, close_loop=False)
    except Exception:
        logger.error("Telegram bot crashed", exc_info=True)
