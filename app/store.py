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
    est_rx  INTEGER NOT NULL DEFAULT 0, -- part of rx spread over a gap with no snapshots
    est_tx  INTEGER NOT NULL DEFAULT 0, -- part of tx spread over a gap with no snapshots
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
    time    TEXT,                       -- time of the last snapshot
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


# Bump when the stored data's meaning changes; stats.db is then rebuilt from
# WGDashboard's history on the next import (derived data only, nothing is lost).
SCHEMA_VERSION = "2"
DERIVED = ("hourly", "cursor", "peer_state", "peers")


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if not row or row[0] != SCHEMA_VERSION:
        with conn:
            for t in DERIVED:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)", (SCHEMA_VERSION,))
    conn.executescript(SCHEMA)
    return conn
