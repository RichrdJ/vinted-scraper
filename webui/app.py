"""Flask web dashboard for vinted-scraper.

Provides pages to manage searches, edit configuration, browse found items and read
logs, plus an RSS feed at ``/feed.xml``. Optional HTTP basic auth is enabled by
setting ``WEB_USERNAME`` / ``WEB_PASSWORD``.
"""
import os
import time
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, Response, abort, flash, redirect, render_template, request, url_for,
)

import config
import db
import notifiers
import proxies
from logger import get_log_path, get_logger
from notifiers.base import Notification

logger = get_logger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24).hex())

# Parameters editable from the config page.
EDITABLE = [
    "items_per_query", "refresh_minutes", "banwords",
    "telegram_enabled", "telegram_token", "telegram_chat_id",
    "ntfy_enabled", "ntfy_server", "ntfy_topic", "ntfy_token", "ntfy_priority",
    "rss_enabled", "rss_max_items",
    "proxy_list", "proxy_list_link", "check_proxies",
]
CHECKBOXES = {"telegram_enabled", "ntfy_enabled", "rss_enabled", "check_proxies"}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _check_auth(auth) -> bool:
    return (
        auth is not None
        and auth.username == config.WEB_USERNAME
        and auth.password == config.WEB_PASSWORD
    )


def requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if config.WEB_USERNAME and not _check_auth(request.authorization):
            return Response(
                "Authentication required.", 401,
                {"WWW-Authenticate": 'Basic realm="vinted-scraper"'},
            )
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def _inject_globals():
    return {"version": config.VERSION}


@app.template_filter("ago")
def _format_ago(ts):
    if not ts:
        return "never"
    seconds = max(0, int(time.time()) - int(ts))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


@app.template_filter("dt")
def _format_dt(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
@requires_auth
def index():
    return render_template(
        "index.html",
        stats=db.get_stats(),
        notifiers=[n.name for n in notifiers.enabled_notifiers()],
        refresh=db.get_refresh_minutes(),
        rss_enabled=db.get_bool("rss_enabled"),
    )


@app.route("/queries", methods=["GET", "POST"])
@requires_auth
def queries():
    import scraper

    if request.method == "POST":
        name = (request.form.get("name") or "").strip() or None
        keyword = (request.form.get("keyword") or "").strip()
        url = (request.form.get("url") or "").strip()
        if keyword:
            url = scraper.build_search_url(
                keyword,
                domain=request.form.get("domain") or "www.vinted.nl",
                price_from=request.form.get("price_from"),
                price_to=request.form.get("price_to"),
            )
            name = name or keyword
        if url:
            message, _ = scraper.add_query(url, name)
            flash(message)
        else:
            flash("Enter a search term or a Vinted URL.")
        return redirect(url_for("queries"))
    return render_template(
        "queries.html",
        queries=db.get_queries(),
        domains=scraper.DOMAINS,
        scanning=scraper.is_scanning(),
    )


@app.route("/queries/<int:query_id>/delete", methods=["POST"])
@requires_auth
def delete_query(query_id):
    db.remove_query(query_id)
    flash("Search removed.")
    return redirect(url_for("queries"))


@app.route("/queries/<int:query_id>/edit", methods=["GET", "POST"])
@requires_auth
def edit_query(query_id):
    import scraper

    query = db.get_query(query_id)
    if query is None:
        abort(404)
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        name = (request.form.get("name") or "").strip() or None
        message, ok = scraper.update_search(query_id, url, name)
        flash(message)
        if ok:
            return redirect(url_for("queries"))
        return redirect(url_for("edit_query", query_id=query_id))
    return render_template("edit_query.html", query=query)


@app.route("/queries/<int:query_id>/scan", methods=["POST"])
@requires_auth
def scan_query(query_id):
    import scraper

    _, message = scraper.scan_now(query_id)
    flash(message)
    return redirect(url_for("queries"))


@app.route("/queries/scan-all", methods=["POST"])
@requires_auth
def scan_all():
    import scraper

    _, message = scraper.scan_all_async()
    flash(message)
    return redirect(url_for("queries"))


@app.route("/items")
@requires_auth
def items():
    q = (request.args.get("q") or "").strip()
    query_id = request.args.get("query", type=int)
    return render_template(
        "items.html",
        items=db.get_items(limit=240, query_id=query_id, search=q or None),
        q=q,
        query_id=query_id,
        queries=db.get_queries(),
    )


@app.route("/config", methods=["GET", "POST"])
@requires_auth
def config_page():
    if request.method == "POST":
        for key in EDITABLE:
            if key in CHECKBOXES:
                db.set_parameter(key, "True" if request.form.get(key) else "False")
            elif key in request.form:
                db.set_parameter(key, request.form.get(key).strip())

        # Enforce the minimum interval: polling faster gets you banned by Vinted.
        try:
            minutes = int(request.form.get("refresh_minutes", db.MIN_REFRESH_MINUTES))
        except ValueError:
            minutes = db.MIN_REFRESH_MINUTES
        if minutes < db.MIN_REFRESH_MINUTES:
            flash(f"Refresh interval raised to the minimum of {db.MIN_REFRESH_MINUTES} minutes.")
            minutes = db.MIN_REFRESH_MINUTES
        db.set_parameter("refresh_minutes", str(minutes))

        proxies.invalidate_cache()
        flash("Configuration saved.")
        return redirect(url_for("config_page"))

    params = db.get_all_parameters()
    return render_template(
        "config.html",
        params=params,
        allowlist=db.get_allowlist(),
        refresh_minutes=db.get_refresh_minutes(),
        min_refresh=db.MIN_REFRESH_MINUTES,
    )


@app.route("/allowlist", methods=["POST"])
@requires_auth
def allowlist():
    action = request.form.get("action")
    country = (request.form.get("country") or "").strip()
    if len(country) == 2:
        if action == "remove":
            db.remove_from_allowlist(country)
        else:
            db.add_to_allowlist(country)
    return redirect(url_for("config_page"))


@app.route("/test-notification", methods=["POST"])
@requires_auth
def test_notification():
    notifiers.dispatch(
        Notification(
            title="Test notification from vinted-scraper",
            price_label="0 EUR",
            brand="vinted-scraper",
            size=None,
            url="https://www.vinted.nl/",
            photo_url=None,
            query_name="test",
        )
    )
    flash("Test notification sent to all enabled channels.")
    return redirect(url_for("config_page"))


@app.route("/logs")
@requires_auth
def logs():
    path = get_log_path()
    content = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        content = "".join(lines[-400:])
    return render_template("logs.html", content=content)


@app.route("/feed.xml")
def feed():
    if not db.get_bool("rss_enabled"):
        abort(404)
    from feedgen.feed import FeedGenerator

    fg = FeedGenerator()
    fg.title("vinted-scraper — new listings")
    fg.link(href=request.url_root, rel="alternate")
    fg.description("New Vinted listings matching your saved searches")
    fg.language("en")

    max_items = db.get_int("rss_max_items", 100)
    for item in db.get_items(limit=max_items):
        fe = fg.add_entry()
        fe.id(str(item["id"]))
        fe.title(f"{item['title']} — {item['price']} {item['currency']}")
        fe.link(href=item["item_url"] or request.url_root)
        desc = f"{item['price']} {item['currency']}"
        if item["brand"]:
            desc += f" · {item['brand']}"
        if item["size"]:
            desc += f" · size {item['size']}"
        if item["photo_url"]:
            desc += f'<br><img src="{item["photo_url"]}">'
        fe.description(desc)
        if item["found_at"]:
            fe.pubDate(datetime.fromtimestamp(int(item["found_at"]), tz=timezone.utc))

    return Response(fg.rss_str(pretty=True), mimetype="application/rss+xml")


def run_web():
    logger.info("Web UI on http://%s:%s", config.WEB_HOST, config.WEB_PORT)
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True, use_reloader=False)
