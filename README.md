# wgdashboard-stats

Traffic reports for [WGDashboard](https://github.com/WGDashboard/WGDashboard): pick a WireGuard configuration and any date range, and see how much each peer sent and received, with a daily chart and CSV export.

WGDashboard only shows lifetime totals per peer. It does, however, record a snapshot of every running peer's counters about once a minute (the `<config>_transfer` tables, when peer tracking is on). This app reads those snapshots **read-only**, turns them into hourly usage per peer, and serves a small web page on top.

| Phone (dark mode) | Desktop |
| --- | --- |
| <img src="docs/screenshot-mobile.png" width="260"> | <img src="docs/screenshot-desktop.png" width="560"> |

## Features

- Date range picker with presets: this month, last month, last 30 days, this year
- Sent / received / total for the period, per peer and overall
- Daily stacked chart; tap a peer to see only its days
- Sortable peer table with share of total, restricted and deleted peers included
- CSV export for the selected range
- Light and dark mode, works on phones; the selection is kept in the URL
- Never writes to WGDashboard's database

## Run it

WGDashboard must have peer tracking turned on (global setting and per configuration), otherwise there are no snapshots to read. Your history goes back as far as WGDashboard has been recording.

```bash
mkdir -p wgdashboard-stats && cd wgdashboard-stats
curl -O https://raw.githubusercontent.com/shuricksumy/wgdashboard-stats/main/docker-compose.ghcr.yml
# edit the WGDashboard db path, hostname and Traefik labels, then:
docker compose -f docker-compose.ghcr.yml up -d
docker logs -f wgdashboard-stats   # first import of a year of history takes a few seconds
```

Or build locally with `docker compose up -d --build` using [docker-compose.yml](docker-compose.yml).

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `WGD_DB` | `/data/wgdashboard.db` | WGDashboard's SQLite database (mount its folder read-only) |
| `STATS_DB` | `/state/stats.db` | The app's own database of hourly totals |
| `INGEST_INTERVAL` | `600` | Seconds between imports (`0` disables the background import) |
| `TZ` | `UTC` | Timezone for "data updated" times; WGDashboard stores local time |
| `PORT` | `8080` | HTTP port |
| `LOG_LEVEL` | `INFO` | Python log level |

`stats.db` can be deleted at any time; it is rebuilt from WGDashboard's history on the next import.

## How usage is calculated

Each snapshot holds lifetime counters (`cumu_*` + `total_*`, in GB). Usage is the increase between consecutive snapshots of the same peer. Three traps are handled, and covered by tests:

- **Clock changes.** WGDashboard stores naive local time, so when clocks go back an hour, two copies of that hour interleave if you sort by time. Snapshots are processed in insertion order (`rowid`) instead.
- **Tiny dips.** Float noise and interleaving can make a counter look like it went down by a few bytes. Dips are ignored and the highest value seen stays the baseline, so nothing is counted twice.
- **Real resets.** "Reset data usage" in WGDashboard, or a counter restart, drops the counter below half of its baseline. The new value is counted as fresh usage.

If WGDashboard clears or vacuums the transfer table, the import resumes by timestamp.

## API

| Endpoint | Returns |
| --- | --- |
| `GET /api/configs` | Configurations with peer count and data range |
| `GET /api/usage?config=wg0&start=2026-10-01&end=2026-10-31[&peer=<public key>]` | Totals, per-peer usage, daily series (bytes) |
| `GET /api/usage.csv?config=wg0&start=…&end=…` | Per-peer CSV |
| `GET /api/status` | Last import time and position per configuration |
| `POST /api/refresh` | Import now |
| `GET /healthz` | Health check |

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q

# demo data (two months of minute snapshots) and a local server
python tools/make_demo_db.py demo/wgdashboard.db
WGD_DB=demo/wgdashboard.db STATS_DB=demo/stats.db uvicorn app.main:app --reload
```

## Not yet

PostgreSQL / MySQL support (WGDashboard 4.3+ can use them), monthly and online-time views, connection IP history, PDF reports.

## License

MIT
