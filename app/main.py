"""FastAPI app: background ingest, JSON/CSV API and the web page."""
import csv
import io
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import queries, store
from app.ingest import GB, ingest_all

WGD_DB = os.environ.get("WGD_DB", "/data/wgdashboard.db")
STATS_DB = os.environ.get("STATS_DB", "/state/stats.db")
INTERVAL = int(os.environ.get("INGEST_INTERVAL", "600"))
STATIC = Path(__file__).parent / "static"

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("wgstats")

_lock = threading.Lock()
_stop = threading.Event()
db = None


def run_ingest() -> dict:
    with _lock:
        return ingest_all(WGD_DB, db)


def _loop():
    while not _stop.is_set():
        try:
            run_ingest()
        except Exception:
            log.exception("ingest failed")
        _stop.wait(INTERVAL)


@asynccontextmanager
async def lifespan(_app):
    global db
    db = store.connect(STATS_DB)
    if INTERVAL > 0:
        threading.Thread(target=_loop, name="ingest", daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="wgdashboard-stats", lifespan=lifespan)


def _range(start: date, end: date):
    if end < start:
        raise HTTPException(400, "end is before start")
    if (end - start).days > 3660:
        raise HTTPException(400, "range is too long")


@app.get("/api/configs")
def api_configs():
    with _lock:
        return queries.configs(db)


@app.get("/api/usage")
def api_usage(config: str, start: date, end: date, peer: str | None = Query(None)):
    _range(start, end)
    with _lock:
        return queries.usage(db, config, start, end, peer)


@app.get("/api/usage.csv")
def api_usage_csv(config: str, start: date, end: date):
    _range(start, end)
    with _lock:
        data = queries.usage(db, config, start, end)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["peer", "status", "public_key", "received_gb", "sent_gb", "total_gb", "received_bytes", "sent_bytes", "estimated_gb"])
    for p in data["peers"]:
        w.writerow([p["name"], p["status"], p["id"], f"{p['rx'] / GB:.3f}", f"{p['tx'] / GB:.3f}",
                    f"{(p['rx'] + p['tx']) / GB:.3f}", p["rx"], p["tx"], f"{(p['est_rx'] + p['est_tx']) / GB:.3f}"])
    t = data["totals"]
    w.writerow(["TOTAL", "", "", f"{t['rx'] / GB:.3f}", f"{t['tx'] / GB:.3f}", f"{(t['rx'] + t['tx']) / GB:.3f}", t["rx"], t["tx"],
                f"{(t['est_rx'] + t['est_tx']) / GB:.3f}"])
    name = f"wg-usage_{config}_{start}_{end}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/status")
def api_status():
    with _lock:
        return queries.status(db)


@app.post("/api/refresh")
def api_refresh():
    return {"ingested": run_ingest()}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
