"""Create a demo WGDashboard-like database with a few months of minute snapshots."""
import math, random, sys
from datetime import datetime, timedelta
sys.path.insert(0, ".")
from tests.fakewgd import FakeWGD

out = sys.argv[1] if len(sys.argv) > 1 else "demo/wgdashboard.db"
random.seed(7)
w = FakeWGD(out).add_config("wg0").add_config("wg1")
peers = {"K1": ("home-server", 0.004, ""), "K2": ("media-box", 0.0012, ""),
         "K3": ("alice-phone", 0.0006, ""), "K4": ("guest-laptop", 0.0002, "_restrict_access")}
for pid, (name, _, where) in peers.items():
    w.add_peer("wg0", pid, name, where)
w.add_peer("wg1", "Z1", "office-router")
counters = {p: [0.0, 0.0] for p in list(peers) + ["Z1"]}
t = datetime(2026, 9, 1)
rows = []
while t < datetime(2026, 11, 13, 9):
    hour_factor = 0.3 + math.sin((t.hour - 6) / 24 * math.pi) ** 2
    for pid in counters:
        rate = peers[pid][1] if pid in peers else 0.0008
        counters[pid][0] += rate * hour_factor * random.uniform(0.2, 1.8)
        counters[pid][1] += rate * 0.35 * hour_factor * random.uniform(0.2, 1.8)
        cfg = "wg1" if pid == "Z1" else "wg0"
        if not (datetime(2026, 10, 10, 9) <= t < datetime(2026, 10, 15, 14)):  # WGDashboard "down"
            rows.append((cfg, pid, t.strftime("%Y-%m-%d %H:%M:%S.%f"), *counters[pid]))
    t += timedelta(minutes=1)
for cfg in ("wg0", "wg1"):
    w.conn.executemany(
        f'INSERT INTO "{cfg}_transfer" (id, total_receive, total_sent, total_data, cumu_receive, cumu_sent, cumu_data, time) '
        f"VALUES (?, ?, ?, ?, 0, 0, 0, ?)",
        [(r[1], r[3], r[4], r[3] + r[4], r[2]) for r in rows if r[0] == cfg])
w.conn.commit()
print(out, len(rows), "snapshots")
