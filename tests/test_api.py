import importlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.fakewgd import FakeWGD


@pytest.fixture
def client(tmp_path, monkeypatch):
    wgd = FakeWGD(tmp_path / "wgdashboard.db").add_config("wg0")
    wgd.add_peer("wg0", "A", "Phone")
    wgd.add_peer("wg0", "B", "Laptop", "_restrict_access")
    for t, a, b in [("2026-09-30 23:00", 0, 0), ("2026-10-01 10:00", 1, 0.5), ("2026-10-02 10:00", 3, 1),
                    ("2026-11-01 00:30", 4, 2)]:
        wgd.snap("wg0", "A", t, a, a / 2)
        wgd.snap("wg0", "B", t, b, b)
    monkeypatch.setenv("WGD_DB", wgd.path)
    monkeypatch.setenv("STATS_DB", str(tmp_path / "stats.db"))
    monkeypatch.setenv("INGEST_INTERVAL", "0")
    monkeypatch.setattr("app.ingest.GAP", timedelta(days=365))  # sparse fixture: keep usage on its day
    import app.main as m
    importlib.reload(m)
    with TestClient(m.app) as c:
        c.post("/api/refresh")
        yield c


GB = 1024 ** 3


def test_usage_for_october(client):
    r = client.get("/api/usage", params={"config": "wg0", "start": "2026-10-01", "end": "2026-10-31"}).json()
    peers = {p["name"]: (p["rx"] / GB, p["tx"] / GB, p["status"]) for p in r["peers"]}
    assert peers == {"Phone": (3.0, 1.5, "active"), "Laptop": (1.0, 1.0, "restricted")}
    assert r["totals"] == {"rx": 4 * GB, "tx": round(2.5 * GB), "est_rx": 0, "est_tx": 0}
    assert len(r["daily"]) == 31
    assert r["daily"][0] == {"day": "2026-10-01", "rx": 1.5 * GB, "tx": 1.0 * GB, "est_rx": 0, "est_tx": 0}
    assert r["daily"][5]["rx"] == 0


def test_daily_for_one_peer(client):
    r = client.get("/api/usage", params={"config": "wg0", "start": "2026-10-01", "end": "2026-10-02", "peer": "B"}).json()
    assert [d["rx"] / GB for d in r["daily"]] == [0.5, 0.5]


def test_csv(client):
    r = client.get("/api/usage.csv", params={"config": "wg0", "start": "2026-10-01", "end": "2026-10-31"})
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("peer,status")
    assert lines[1].startswith("Phone,active,A,3.000,1.500,4.500")
    assert lines[-1].startswith("TOTAL,,,4.000,2.500,6.500")


def test_configs_status_and_validation(client):
    assert client.get("/api/configs").json()[0]["name"] == "wg0"
    assert client.get("/api/status").json()["last_ingest"]
    bad = client.get("/api/usage", params={"config": "wg0", "start": "2026-10-05", "end": "2026-10-01"})
    assert bad.status_code == 400
    assert client.get("/").status_code == 200


def test_base_path(tmp_path, monkeypatch):
    wgd = FakeWGD(tmp_path / "wgdashboard.db").add_config("wg0")
    monkeypatch.setenv("WGD_DB", wgd.path)
    monkeypatch.setenv("STATS_DB", str(tmp_path / "stats.db"))
    monkeypatch.setenv("INGEST_INTERVAL", "0")
    monkeypatch.setenv("BASE_PATH", "/wgstat/")
    import app.main as m
    importlib.reload(m)
    try:
        with TestClient(m.app) as c:
            assert c.get("/wgstat/").status_code == 200
            assert c.get("/wgstat/static/chart.umd.min.js").status_code == 200
            assert c.post("/wgstat/api/refresh").status_code == 200
            assert c.get("/wgstat/api/configs").status_code == 200
            for path in ("/wgstat", "/"):
                r = c.get(path, follow_redirects=False)
                assert r.status_code == 307 and r.headers["location"] == "/wgstat/"
            assert c.get("/api/configs").status_code == 404
            assert c.get("/healthz").status_code == 200
    finally:
        monkeypatch.delenv("BASE_PATH")
        importlib.reload(m)
