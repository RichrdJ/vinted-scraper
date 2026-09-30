"""SQLite persistence layer.

A fresh connection is opened per call (SQLite handles this well for our low write
volume) which keeps the module trivially thread-safe across the scraper, web UI and
notifier threads. All configuration lives in the ``parameters`` table so it can be
edited at runtime from the web UI.
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vinted-scraper.db"),
)
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the database and apply the schema (idempotent)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        script = fh.read()
    with _connect() as conn:
        conn.executescript(script)
        _migrate(conn)
    logger.info("Database ready at %s", DB_PATH)


# Columns added after the first release: (table, column, type).
_ADDED_COLUMNS = [
    ("queries", "last_scan_at", "INTEGER"),
    ("queries", "last_scan_result", "TEXT"),
]


def _migrate(conn) -> None:
    for table, column, col_type in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info("Migrated: added %s.%s", table, column)


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
def get_parameter(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT value FROM parameters WHERE key=?", (key,)
            ).fetchone()
    except sqlite3.OperationalError:
        # Table not created yet (e.g. accessed before init_db()).
        return default
    return row["value"] if row else default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_parameter(key, str(default)))
    except (TypeError, ValueError):
        return default


MIN_REFRESH_MINUTES = 5  # polling faster gets IPs banned by Vinted


def get_refresh_minutes() -> int:
    """Refresh interval in minutes, never below MIN_REFRESH_MINUTES."""
    return max(MIN_REFRESH_MINUTES, get_int("refresh_minutes", MIN_REFRESH_MINUTES))


def get_bool(key: str) -> bool:
    return (get_parameter(key) or "").strip().lower() in ("true", "1", "yes", "on")


def set_parameter(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO parameters (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def get_all_parameters() -> Dict[str, str]:
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM parameters").fetchall()
    return {r["key"]: r["value"] for r in rows}


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def add_query(url: str, name: Optional[str] = None) -> bool:
    """Insert a query. Returns True if newly added, False if it already existed."""
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO queries (url, name, last_item) VALUES (?, ?, NULL)",
                (url, name),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def query_exists(url: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM queries WHERE url=?", (url,)).fetchone()
    return row is not None


_QUERY_COLUMNS = "id, url, name, last_item, created_at, last_scan_at, last_scan_result"


def get_queries() -> List[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            f"SELECT {_QUERY_COLUMNS} FROM queries ORDER BY id"
        ).fetchall()


def get_query(query_id: int) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            f"SELECT {_QUERY_COLUMNS} FROM queries WHERE id=?", (query_id,)
        ).fetchone()


def update_query(
    query_id: int, url: str, name: Optional[str], reset_progress: bool = False
) -> bool:
    """Update a query. Returns False if another query already uses ``url``.

    With ``reset_progress`` the high-water mark is cleared, so the next scan
    re-seeds silently instead of notifying about everything under the new URL.
    """
    sql = "UPDATE queries SET url=?, name=?"
    if reset_progress:
        sql += ", last_item=NULL, last_scan_at=NULL, last_scan_result=NULL"
    sql += " WHERE id=?"
    try:
        with _connect() as conn:
            conn.execute(sql, (url, name, query_id))
        return True
    except sqlite3.IntegrityError:
        return False


def set_scan_result(query_id: int, result: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE queries SET last_scan_at=?, last_scan_result=? WHERE id=?",
            (int(time.time()), result, query_id),
        )


def remove_query(query_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM queries WHERE id=?", (query_id,))


def remove_all_queries() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM queries")


def get_last_timestamp(query_id: int) -> Optional[int]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_item FROM queries WHERE id=?", (query_id,)
        ).fetchone()
    return row["last_item"] if row and row["last_item"] is not None else None


def update_last_timestamp(query_id: int, timestamp: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE queries SET last_item=? WHERE id=? AND "
            "(last_item IS NULL OR last_item < ?)",
            (timestamp, query_id, timestamp),
        )


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
def item_exists(item_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone()
    return row is not None


def add_item(
    item_id: int,
    query_id: int,
    title: str,
    price: Any,
    currency: str,
    brand: Optional[str],
    size: Optional[str],
    photo_url: Optional[str],
    item_url: str,
    timestamp: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO items "
            "(id, query_id, title, price, currency, brand, size, photo_url, item_url, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, query_id, title, price, currency, brand, size, photo_url, item_url, timestamp),
        )
        conn.execute(
            "UPDATE queries SET last_item=? WHERE id=? AND "
            "(last_item IS NULL OR last_item < ?)",
            (timestamp, query_id, timestamp),
        )


def get_items(
    limit: int = 100, query_id: Optional[int] = None, search: Optional[str] = None
) -> List[sqlite3.Row]:
    sql = (
        "SELECT i.*, q.name AS query_name, q.url AS query_url "
        "FROM items i LEFT JOIN queries q ON i.query_id = q.id "
    )
    where: List[str] = []
    params: Tuple = ()
    if query_id is not None:
        where.append("i.query_id=?")
        params += (query_id,)
    if search:
        like = f"%{search}%"
        where.append("(i.title LIKE ? OR i.brand LIKE ? OR i.size LIKE ?)")
        params += (like, like, like)
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY i.found_at DESC, i.timestamp DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return conn.execute(sql, params).fetchall()


# --------------------------------------------------------------------------- #
# Allowlist (seller country ISO codes; empty = allow all)
# --------------------------------------------------------------------------- #
def get_allowlist() -> List[str]:
    with _connect() as conn:
        rows = conn.execute("SELECT country FROM allowlist ORDER BY country").fetchall()
    return [r["country"] for r in rows]


def add_to_allowlist(country: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO allowlist (country) VALUES (?)", (country.upper(),))


def remove_from_allowlist(country: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM allowlist WHERE country=?", (country.upper(),))


# --------------------------------------------------------------------------- #
# Stats (dashboard)
# --------------------------------------------------------------------------- #
def get_stats() -> Dict[str, Any]:
    with _connect() as conn:
        total_items = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        total_queries = conn.execute("SELECT COUNT(*) c FROM queries").fetchone()["c"]
        bounds = conn.execute(
            "SELECT MIN(found_at) mn, MAX(found_at) mx FROM items"
        ).fetchone()
        last = conn.execute(
            "SELECT title, price, currency, item_url, found_at FROM items "
            "ORDER BY found_at DESC LIMIT 1"
        ).fetchone()

    per_day = 0.0
    if total_items and bounds and bounds["mn"]:
        span_days = max(1, (bounds["mx"] - bounds["mn"]) / 86400)
        per_day = round(total_items / span_days, 1)

    return {
        "total_items": total_items,
        "total_queries": total_queries,
        "items_per_day": per_day,
        "last_item": dict(last) if last else None,
    }
