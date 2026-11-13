"""Read WGDashboard's traffic snapshots and turn them into hourly usage per peer.

WGDashboard writes one row per running peer into `<config>_transfer` about once a
minute. Each row holds lifetime counters (cumu_* + total_*, in GB). Usage is the
increase between consecutive snapshots of the same peer, with three traps handled:

* Rows are processed in insertion order (rowid), not by `time`. The time column is
  naive local time, so when clocks go back an hour, sorting by time interleaves two
  copies of that hour.
* Small dips (float noise, interleaving) are ignored, and the highest value seen is
  kept as the baseline so the same traffic is never counted twice.
* A drop to below half of the baseline is a real reset (usage reset in the UI, or a
  counter restart), and the new value is counted as fresh usage.
"""
import logging
import sqlite3
import time

log = logging.getLogger("wgstats.ingest")

GB = 1024 ** 3
RESET_RATIO = 0.5
BATCH = 20000
PEER_TABLES = (("", "active"), ("_restrict_access", "restricted"), ("_deleted", "deleted"))


def open_source(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def discover_configs(src: sqlite3.Connection) -> list[str]:
    names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    configs = []
    for n in sorted(names):
        if n.endswith("_transfer") and not n.startswith("."):
            base = n[: -len("_transfer")]
            if base in names:
                configs.append(base)
    return configs


def step(prev: float | None, cur: float) -> tuple[float, float]:
    """Return (usage in GB, new baseline) for one counter."""
    if cur is None:
        return 0.0, prev
    if prev is None:
        return 0.0, cur
    if cur < prev * RESET_RATIO:
        return cur, cur
    if cur < prev:
        return 0.0, prev
    return cur - prev, cur


def hour_of(t: str) -> str:
    t = str(t).replace("T", " ")
    return t[:13] + ":00"


def refresh_peers(src, dst, config: str) -> None:
    seen = {}
    for suffix, status in PEER_TABLES:
        try:
            rows = src.execute(f'SELECT id, name FROM "{config}{suffix}"').fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            seen.setdefault(r["id"], (r["name"], status))
    dst.executemany(
        "INSERT INTO peers (config, peer_id, name, status) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(config, peer_id) DO UPDATE SET name=excluded.name, status=excluded.status",
        [(config, pid, name, status) for pid, (name, status) in seen.items()],
    )
    # Peers that vanished from all WGDashboard tables keep their history but are marked.
    if seen:
        marks = ",".join("?" * len(seen))
        dst.execute(
            f"UPDATE peers SET status='unknown' WHERE config=? AND peer_id NOT IN ({marks})",
            (config, *seen.keys()),
        )


def _start_rowid(src, dst, config: str) -> int:
    cur = dst.execute("SELECT last_rowid, last_time FROM cursor WHERE config=?", (config,)).fetchone()
    if not cur:
        return 0
    max_rowid = src.execute(f'SELECT MAX(rowid) FROM "{config}_transfer"').fetchone()[0] or 0
    if max_rowid >= cur["last_rowid"]:
        return cur["last_rowid"]
    # Rowids went backwards: the table was vacuumed or cleared. Resume by time instead.
    log.warning("%s: rowids renumbered, resuming after %s", config, cur["last_time"])
    r = src.execute(
        f'SELECT MIN(rowid) FROM "{config}_transfer" WHERE time > ?', (cur["last_time"],)
    ).fetchone()[0]
    return (r - 1) if r is not None else max_rowid


def ingest_config(src, dst, config: str) -> int:
    refresh_peers(src, dst, config)
    start = _start_rowid(src, dst, config)
    state = {
        r["peer_id"]: [r["rx"], r["tx"]]
        for r in dst.execute("SELECT peer_id, rx, tx FROM peer_state WHERE config=?", (config,))
    }
    total = 0
    while True:
        rows = src.execute(
            f'SELECT rowid AS rid, id, time, '
            f'COALESCE(cumu_receive,0)+COALESCE(total_receive,0) AS rx, '
            f'COALESCE(cumu_sent,0)+COALESCE(total_sent,0) AS tx '
            f'FROM "{config}_transfer" WHERE rowid > ? ORDER BY rowid LIMIT ?',
            (start, BATCH),
        ).fetchall()
        if not rows:
            break
        buckets: dict[tuple[str, str], list[float]] = {}
        for r in rows:
            prev = state.get(r["id"], [None, None])
            drx, brx = step(prev[0], r["rx"])
            dtx, btx = step(prev[1], r["tx"])
            state[r["id"]] = [brx, btx]
            if drx or dtx:
                b = buckets.setdefault((r["id"], hour_of(r["time"])), [0.0, 0.0])
                b[0] += drx
                b[1] += dtx
        last = rows[-1]
        with dst:
            dst.executemany(
                "INSERT INTO hourly (config, peer_id, hour, rx, tx) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(config, peer_id, hour) DO UPDATE SET rx=rx+excluded.rx, tx=tx+excluded.tx",
                [(config, pid, h, round(v[0] * GB), round(v[1] * GB)) for (pid, h), v in buckets.items()],
            )
            dst.executemany(
                "INSERT INTO peer_state (config, peer_id, rx, tx) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(config, peer_id) DO UPDATE SET rx=excluded.rx, tx=excluded.tx",
                [(config, pid, v[0], v[1]) for pid, v in state.items() if v[0] is not None],
            )
            dst.execute(
                "INSERT INTO cursor (config, last_rowid, last_time) VALUES (?, ?, ?) "
                "ON CONFLICT(config) DO UPDATE SET last_rowid=excluded.last_rowid, last_time=excluded.last_time",
                (config, last["rid"], str(last["time"])),
            )
        start = last["rid"]
        total += len(rows)
    return total


def ingest_all(source_path: str, dst) -> dict[str, int]:
    started = time.time()
    src = open_source(source_path)
    try:
        result = {c: ingest_config(src, dst, c) for c in discover_configs(src)}
    finally:
        src.close()
    with dst:
        dst.execute(
            "INSERT INTO meta (key, value) VALUES ('last_ingest', datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
    log.info("ingested %s in %.1fs", result, time.time() - started)
    return result
