"""Accès SQLite partagé entre l'API et le serveur MCP (même volume Docker, mode WAL)."""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    watch TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT, company TEXT, location TEXT, contract TEXT, remote TEXT, salary TEXT,
    skills TEXT, summary TEXT, contact TEXT, published TEXT,
    score INTEGER, reasons TEXT, red_flags TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    found_at TEXT NOT NULL,
    run_id INTEGER,
    source TEXT,
    kept INTEGER NOT NULL DEFAULT 1,
    query TEXT
);
CREATE INDEX IF NOT EXISTS idx_offers_watch ON offers(watch, found_at);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);

CREATE TABLE IF NOT EXISTS seen_urls (
    url_hash TEXT NOT NULL,
    watch TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (url_hash, watch)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats TEXT,
    events TEXT,
    report_path TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_watch ON runs(watch, started_at);

CREATE TABLE IF NOT EXISTS page_cache (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    published TEXT,
    content TEXT,
    structured TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    timelimit TEXT,
    embedding BLOB,
    results TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    task TEXT NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls ON llm_calls(provider, model, ts);

CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MIGRATIONS = [("page_cache", "structured", "TEXT"), ("offers", "source", "TEXT"),
              ("offers", "kept", "INTEGER NOT NULL DEFAULT 1"), ("offers", "query", "TEXT")]

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                   "fbclid", "gclid", "ref", "refid", "trk", "mc_cid", "mc_eid"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migrations légères pour les bases créées par une version précédente
        for table, column, kind in MIGRATIONS:
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def normalize_url(url: str) -> str:
    """Normalise une URL pour la déduplication (sans fragment ni paramètres de suivi)."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:24]
