"""Read-side queries on stats.db."""
from datetime import date, timedelta


def _bounds(start: date, end: date) -> tuple[str, str]:
    return f"{start.isoformat()} 00:00", f"{(end + timedelta(days=1)).isoformat()} 00:00"


def configs(db) -> list[dict]:
    rows = db.execute(
        "SELECT c.config AS name, "
        "  (SELECT COUNT(*) FROM peers p WHERE p.config=c.config) AS peers, "
        "  (SELECT MIN(hour) FROM hourly h WHERE h.config=c.config) AS first, "
        "  (SELECT MAX(hour) FROM hourly h WHERE h.config=c.config) AS last "
        "FROM cursor c ORDER BY c.config"
    ).fetchall()
    return [dict(r) for r in rows]


def usage(db, config: str, start: date, end: date, peer: str | None = None) -> dict:
    lo, hi = _bounds(start, end)
    peers = [
        dict(r)
        for r in db.execute(
            "SELECT h.peer_id AS id, COALESCE(p.name, substr(h.peer_id, 1, 10)) AS name, "
            "  COALESCE(p.status, 'unknown') AS status, SUM(h.rx) AS rx, SUM(h.tx) AS tx, "
            "  SUM(h.est_rx) AS est_rx, SUM(h.est_tx) AS est_tx "
            "FROM hourly h LEFT JOIN peers p ON p.config=h.config AND p.peer_id=h.peer_id "
            "WHERE h.config=? AND h.hour>=? AND h.hour<? "
            "GROUP BY h.peer_id HAVING SUM(h.rx)+SUM(h.tx) > 0 "
            "ORDER BY SUM(h.rx)+SUM(h.tx) DESC",
            (config, lo, hi),
        )
    ]
    params = [config, lo, hi]
    peer_sql = ""
    if peer:
        peer_sql = " AND peer_id=?"
        params.append(peer)
    by_day = {
        r["day"]: (r["rx"], r["tx"], r["est_rx"], r["est_tx"])
        for r in db.execute(
            f"SELECT substr(hour, 1, 10) AS day, SUM(rx) AS rx, SUM(tx) AS tx, "
            f"SUM(est_rx) AS est_rx, SUM(est_tx) AS est_tx FROM hourly "
            f"WHERE config=? AND hour>=? AND hour<?{peer_sql} GROUP BY day",
            params,
        )
    }
    daily, d = [], start
    while d <= end:
        rx, tx, erx, etx = by_day.get(d.isoformat(), (0, 0, 0, 0))
        daily.append({"day": d.isoformat(), "rx": rx, "tx": tx, "est_rx": erx, "est_tx": etx})
        d += timedelta(days=1)
    return {
        "config": config,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "peer": peer,
        "totals": {k: sum(p[k] for p in peers) for k in ("rx", "tx", "est_rx", "est_tx")},
        "peers": peers,
        "daily": daily,
    }


def status(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key='last_ingest'").fetchone()
    return {
        "last_ingest": row["value"] if row else None,
        "configs": [dict(r) for r in db.execute("SELECT config, last_rowid, last_time FROM cursor ORDER BY config")],
    }
