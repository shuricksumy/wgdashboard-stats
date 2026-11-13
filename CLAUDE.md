# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small FastAPI app that reads WGDashboard's SQLite database **read-only**, converts its per-minute traffic snapshots (`<config>_transfer` tables) into hourly per-peer usage stored in its own `stats.db`, and serves a single-page UI with date-range reports, a daily chart and CSV export.

## Commands

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                                   # all tests
python tools/make_demo_db.py demo/wgdashboard.db      # demo source DB
WGD_DB=demo/wgdashboard.db STATS_DB=demo/stats.db uvicorn app.main:app --reload
docker compose up -d --build
```

## Layout

- `app/ingest.py` — the important part. Reads new `_transfer` rows **by rowid** (never by `time`: naive local time interleaves at DST fall-back), applies `step()` per counter: tiny dips ignored with the max kept as baseline, a drop below `RESET_RATIO` × baseline is a reset and counts the new value. Cursor per config (`last_rowid`, `last_time`); if rowids go backwards (table cleared/vacuumed) it resumes by time. Also refreshes peer names/status from `<config>`, `_restrict_access`, `_deleted`. If consecutive snapshots of a peer are more than `GAP_MINUTES` apart, the usage is spread over the gap (`spread()`) and also added to `est_rx`/`est_tx`.
- `app/store.py` — schema of `stats.db` (`hourly`, `cursor`, `peer_state`, `peers`, `meta`). Hours are `'YYYY-MM-DD HH:00'` in WGDashboard's local wall-clock time; bytes are integers; `est_*` is the part of `rx`/`tx` that was spread over a gap. Bump `SCHEMA_VERSION` whenever the meaning of stored data changes: stats.db is then dropped and rebuilt from WGDashboard on next start.
- `app/queries.py` — range queries; `end` date is inclusive; daily series is zero-filled.
- `app/main.py` — FastAPI app, background ingest thread every `INGEST_INTERVAL`, one shared SQLite connection guarded by `_lock` (every DB access must take it).
- `app/static/index.html` — the whole UI (vanilla JS, Chart.js bundled locally, relative URLs so it works under a path prefix).
- `tests/fakewgd.py` — builds a DB with WGDashboard's table shapes; add a test there for every new counter edge case.

## Rules

- Never write to WGDashboard's database; it is opened with `mode=ro`.
- WGDashboard values are GB floats (`bytes / 1024**3`); convert to integer bytes at ingest.
- Docker image is published to GHCR by `.github/workflows/docker-publish.yml`: `:dev` from the `dev` branch, `:latest` from `main`, semver from `v*.*.*` tags.
