-- vinted-scraper database schema
-- Executed with executescript(); safe to run repeatedly (IF NOT EXISTS + INSERT OR IGNORE).

PRAGMA foreign_keys = ON;

-- Saved searches to monitor.
CREATE TABLE IF NOT EXISTS queries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL UNIQUE,        -- normalized Vinted catalog URL
    name       TEXT,                        -- optional friendly label
    last_item  INTEGER,                     -- highest item id seen for this query
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    last_scan_at     INTEGER,               -- unix time of the last scan
    last_scan_result TEXT                   -- human-readable outcome of the last scan
);

-- Items we have already seen/notified about (deduplication + history for RSS/UI).
CREATE TABLE IF NOT EXISTS items (
    id        INTEGER PRIMARY KEY,          -- Vinted item id
    query_id  INTEGER,
    title     TEXT,
    price     NUMERIC,
    currency  TEXT,
    brand     TEXT,
    size      TEXT,
    photo_url TEXT,
    item_url  TEXT,
    timestamp INTEGER,                       -- Vinted listing timestamp
    found_at  INTEGER DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (query_id) REFERENCES queries (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_items_query   ON items (query_id);
CREATE INDEX IF NOT EXISTS idx_items_found   ON items (found_at DESC);

-- Optional seller-country allowlist. Empty table = allow all countries.
CREATE TABLE IF NOT EXISTS allowlist (
    country TEXT PRIMARY KEY
);

-- Runtime-editable key/value configuration (mirrors .env at first boot).
CREATE TABLE IF NOT EXISTS parameters (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Default parameters. INSERT OR IGNORE keeps user-edited values on upgrade.
INSERT OR IGNORE INTO parameters (key, value) VALUES
    ('version',              '1.2.0'),
    ('github_url',           'https://github.com/RichrdJ/vinted-scraper'),

    -- Scraping
    ('items_per_query',      '20'),
    ('refresh_minutes',      '5'),    -- minutes between scrape cycles (minimum 5)
    ('banwords',             ''),     -- '|||'-separated words that exclude a listing by title

    -- Telegram
    ('telegram_enabled',     'False'),
    ('telegram_token',       ''),
    ('telegram_chat_id',     ''),

    -- ntfy (https://ntfy.sh or self-hosted)
    ('ntfy_enabled',         'False'),
    ('ntfy_server',          'https://ntfy.sh'),
    ('ntfy_topic',           ''),
    ('ntfy_token',           ''),     -- optional bearer token for protected topics
    ('ntfy_priority',        'default'),

    -- RSS (served by the web UI at /feed.xml)
    ('rss_enabled',          'False'),
    ('rss_max_items',        '100'),

    -- Proxies
    ('proxy_list',           ''),     -- ';'-separated proxies (http://user:pass@host:port)
    ('proxy_list_link',      ''),     -- URL returning a newline-separated proxy list
    ('check_proxies',        'False'),
    ('last_proxy_check_time','0'),

    -- HTTP fingerprint used by the Vinted requester (JSON strings)
    ('user_agents',          '["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"]'),
    ('default_headers',      '{"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9,nl;q=0.8", "Accept-Encoding": "gzip, deflate, br", "Connection": "keep-alive", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}');
