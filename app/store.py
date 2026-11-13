"""The app's own database (stats.db): hourly usage per peer plus ingest state."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly (
    config  TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    hour    TEXT NOT NULL,              -- 'YYYY-MM-DD HH:00', WGDashboard local wall-clock time
    rx      INTEGER NOT NULL DEFAULT 0, -- bytes received by the server from the peer
    tx      INTEGER NOT NULL DEFAULT 0, -- bytes sent by the server to the peer
    PRIMARY KEY (config, peer_id, hour)
);
CREATE INDEX IF NOT EXISTS hourly_config_hour ON hourly (config, hour);

CREATE TABLE IF NOT EXISTS cursor (
    config     TEXT PRIMARY KEY,
    last_rowid INTEGER NOT NULL,
    last_time  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS peer_state (
    config  TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    rx      REAL NOT NULL,              -- highest counter value seen since the last reset (GB)
    tx      REAL NOT NULL,
    PRIMARY KEY (config, peer_id)
);

CREATE TABLE IF NOT EXISTS peers (
    config  TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    name    TEXT,
    status  TEXT NOT NULL,              -- active | restricted | deleted | unknown
    PRIMARY KEY (config, peer_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
