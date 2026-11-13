import pytest

from app import store
from app.ingest import GB, ingest_all, discover_configs, open_source
from tests.fakewgd import FakeWGD


@pytest.fixture
def env(tmp_path):
    wgd = FakeWGD(tmp_path / "wgdashboard.db").add_config("wg0")
    wgd.add_peer("wg0", "A", "Phone")
    dst = store.connect(str(tmp_path / "stats.db"))
    return wgd, dst


def totals(dst, config="wg0"):
    return {
        r["peer_id"]: (round(r["rx"] / GB, 3), round(r["tx"] / GB, 3))
        for r in dst.execute(
            "SELECT peer_id, SUM(rx) rx, SUM(tx) tx FROM hourly WHERE config=? GROUP BY peer_id", (config,)
        )
    }


def test_simple_increments_bucketed_by_hour(env):
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-10-01 10:00:00.1", 1.0, 2.0)
    wgd.snap("wg0", "A", "2026-10-01 10:30:00.1", 1.5, 2.5)
    wgd.snap("wg0", "A", "2026-10-01 11:05:00.1", 3.0, 2.75)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (2.0, 0.75)}
    hours = dict(((r["hour"]), round(r["rx"] / GB, 3)) for r in dst.execute("SELECT hour, rx FROM hourly"))
    assert hours == {"2026-10-01 10:00": 0.5, "2026-10-01 11:00": 1.5}


def test_clock_change_interleaving_is_not_double_counted(env):
    """Clocks go back: the 01:xx hour appears twice, rows are inserted in real order."""
    wgd, dst = env
    vals = [15.0, 15.1, 15.2, 15.3, 15.4]  # true, steadily growing counter
    times = ["2026-10-25 01:10", "2026-10-25 01:40", "2026-10-25 01:05", "2026-10-25 01:35", "2026-10-25 02:05"]
    for t, v in zip(times, vals):
        wgd.snap("wg0", "A", t, v, v)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (0.4, 0.4)}


def test_float_noise_dips_are_ignored(env):
    wgd, dst = env
    for i, v in enumerate([15.93, 15.929999, 15.93, 15.929998, 15.93, 16.0]):
        wgd.snap("wg0", "A", f"2026-10-25 02:{i:02d}:00", v, v)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (0.07, 0.07)}


def test_real_reset_counts_new_traffic(env):
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-10-02 10:00", 10.0, 10.0)
    wgd.snap("wg0", "A", "2026-10-02 10:01", 12.0, 11.0)
    wgd.snap("wg0", "A", "2026-10-02 10:02", 0.5, 0.25)  # usage reset in the UI
    wgd.snap("wg0", "A", "2026-10-02 10:03", 1.0, 0.5)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (3.0, 1.5)}


def test_interface_restart_moves_total_into_cumu(env):
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-10-03 10:00", 5.0, 5.0)
    wgd.snap("wg0", "A", "2026-10-03 10:01", 0.0, 0.0, cumu_rx=5.0, cumu_tx=5.0)
    wgd.snap("wg0", "A", "2026-10-03 10:02", 1.0, 2.0, cumu_rx=5.0, cumu_tx=5.0)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (1.0, 2.0)}


def test_incremental_runs_match_single_run(env, tmp_path):
    wgd, dst = env
    series = [(f"2026-10-04 1{i % 10}:{i:02d}", i * 0.1) for i in range(40)]
    for t, v in series[:25]:
        wgd.snap("wg0", "A", t, v, v / 2)
    ingest_all(wgd.path, dst)
    for t, v in series[25:]:
        wgd.snap("wg0", "A", t, v, v / 2)
    ingest_all(wgd.path, dst)
    ingest_all(wgd.path, dst)  # nothing new: must not change anything
    assert totals(dst) == {"A": (3.9, 1.95)}


def test_rowid_renumbering_resumes_by_time(env):
    wgd, dst = env
    for i in range(5):
        wgd.snap("wg0", "A", f"2026-10-05 10:0{i}", float(i), float(i))
    ingest_all(wgd.path, dst)
    # Simulate WGDashboard clearing the table: rowids restart from 1.
    wgd.conn.execute('DELETE FROM "wg0_transfer"')
    wgd.conn.commit()
    wgd.conn.execute("VACUUM")
    wgd.snap("wg0", "A", "2026-10-05 10:10", 6.0, 6.0)
    wgd.snap("wg0", "A", "2026-10-05 10:11", 7.0, 7.0)
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (7.0, 7.0)}


def test_peer_status_and_names(env):
    wgd, dst = env
    wgd.add_peer("wg0", "B", "Laptop", "_restrict_access")
    wgd.add_peer("wg0", "C", "OldPhone", "_deleted")
    ingest_all(wgd.path, dst)
    peers = {r["peer_id"]: (r["name"], r["status"]) for r in dst.execute("SELECT * FROM peers")}
    assert peers == {"A": ("Phone", "active"), "B": ("Laptop", "restricted"), "C": ("OldPhone", "deleted")}


def test_configs_discovered_and_temp_tables_ignored(env):
    wgd, dst = env
    wgd.add_config("wg1")
    wgd.conn.execute('CREATE TABLE ".#wg0_transfer" (id TEXT)')
    wgd.conn.execute('CREATE TABLE ".#wg0" (id TEXT)')
    wgd.conn.commit()
    assert discover_configs(open_source(wgd.path)) == ["wg0", "wg1"]


def test_source_is_opened_read_only(env):
    wgd, _ = env
    src = open_source(wgd.path)
    with pytest.raises(Exception):
        src.execute("CREATE TABLE x (a)")


def hourly(dst):
    return {
        r["hour"]: (round(r["rx"] / GB, 4), round(r["est_rx"] / GB, 4))
        for r in dst.execute("SELECT hour, rx, est_rx FROM hourly ORDER BY hour")
    }


def test_gap_without_snapshots_is_spread_and_marked_estimated(env):
    """WGDashboard recorded nothing for 4 hours; the jump must not land in one hour."""
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-04-10 10:00:00", 1.0, 1.0)
    wgd.snap("wg0", "A", "2026-04-10 10:30:00", 1.5, 1.5)   # normal minute-level usage
    wgd.snap("wg0", "A", "2026-04-10 14:30:00", 5.5, 5.5)   # +4 GB over a 4 h gap
    ingest_all(wgd.path, dst)
    assert totals(dst) == {"A": (4.5, 4.5)}
    h = hourly(dst)
    assert h == {
        "2026-04-10 10:00": (0.5 + 0.5, 0.5),   # own 0.5 + 30 min of the gap
        "2026-04-10 11:00": (1.0, 1.0),
        "2026-04-10 12:00": (1.0, 1.0),
        "2026-04-10 13:00": (1.0, 1.0),
        "2026-04-10 14:00": (0.5, 0.5),
    }


def test_gap_across_separate_runs(env):
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-04-10 13:59:54", 0.55, 1.96)
    ingest_all(wgd.path, dst)
    wgd.snap("wg0", "A", "2026-10-23 11:00:42", 13.2, 15.83)
    ingest_all(wgd.path, dst)
    h = hourly(dst)
    assert max(v[0] for v in h.values()) < 0.01            # no single-hour spike
    assert totals(dst) == {"A": (12.65, 13.87)}
    assert all(v[0] == v[1] for v in h.values())           # all of it is estimated


def test_short_gap_stays_in_its_hour(env):
    wgd, dst = env
    wgd.snap("wg0", "A", "2026-04-10 10:00", 1.0, 1.0)
    wgd.snap("wg0", "A", "2026-04-10 10:50", 2.0, 2.0)     # 50 min: below GAP_MINUTES
    ingest_all(wgd.path, dst)
    assert hourly(dst) == {"2026-04-10 10:00": (1.0, 0.0)}


def test_old_stats_db_is_rebuilt_on_schema_change(tmp_path):
    path = str(tmp_path / "stats.db")
    c = store.connect(path)
    c.execute("INSERT INTO hourly (config, peer_id, hour, rx, tx) VALUES ('wg0','A','2026-01-01 00:00',1,1)")
    c.execute("UPDATE meta SET value='1' WHERE key='schema'")
    c.commit()
    c.close()
    assert store.connect(path).execute("SELECT COUNT(*) FROM hourly").fetchone()[0] == 0
