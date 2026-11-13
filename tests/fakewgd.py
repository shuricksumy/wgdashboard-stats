"""Builds a small database with the same tables WGDashboard uses."""
import sqlite3

PEER_COLS = ("id TEXT PRIMARY KEY, name TEXT, total_receive REAL, total_sent REAL, "
             "cumu_receive REAL, cumu_sent REAL, preshared_key TEXT")
TRANSFER_COLS = ("id TEXT NOT NULL, total_receive REAL, total_sent REAL, total_data REAL, "
                 "cumu_receive REAL, cumu_sent REAL, cumu_data REAL, time DATETIME")


class FakeWGD:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)

    def add_config(self, name):
        for suffix in ("", "_restrict_access", "_deleted"):
            self.conn.execute(f'CREATE TABLE "{name}{suffix}" ({PEER_COLS})')
        self.conn.execute(f'CREATE TABLE "{name}_transfer" ({TRANSFER_COLS})')
        self.conn.commit()
        return self

    def add_peer(self, config, pid, name, where=""):
        self.conn.execute(f'INSERT INTO "{config}{where}" (id, name) VALUES (?, ?)', (pid, name))
        self.conn.commit()

    def snap(self, config, pid, time, rx, tx, cumu_rx=0.0, cumu_tx=0.0):
        """One snapshot; rx/tx are WGDashboard's total_* columns in GB."""
        self.conn.execute(
            f'INSERT INTO "{config}_transfer" (id, total_receive, total_sent, total_data, '
            f'cumu_receive, cumu_sent, cumu_data, time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (pid, rx, tx, rx + tx, cumu_rx, cumu_tx, cumu_rx + cumu_tx, time),
        )
        self.conn.commit()
