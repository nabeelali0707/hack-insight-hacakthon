"""Read-only serving snapshot of the warehouse for the web app.

The hourly pipeline holds a read-write lock on data/warehouse.duckdb while it runs. The web
API must never block that (or be blocked by it), so it reads data/serve/warehouse.duckdb, a
copy published after every pipeline run (and on demand: `python -m bijlicast.serving`).
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import duckdb

from .config import DATA_DIR, WAREHOUSE_PATH

SERVE_DIR = DATA_DIR / "serve"
SNAPSHOT_PATH = SERVE_DIR / "warehouse.duckdb"


def publish_snapshot(retries: int = 10) -> bool:
    """Checkpoint the warehouse and atomically replace the serving copy. Returns success."""
    if not WAREHOUSE_PATH.exists():
        return False
    try:
        con = duckdb.connect(str(WAREHOUSE_PATH))
        con.execute("CHECKPOINT")
        con.close()
    except duckdb.Error:
        return False  # pipeline is writing right now; the next run publishes
    SERVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SERVE_DIR / "warehouse.duckdb.tmp"
    shutil.copy2(WAREHOUSE_PATH, tmp)
    for _ in range(retries):
        try:
            os.replace(tmp, SNAPSHOT_PATH)
            return True
        except PermissionError:  # Windows: a request has the old snapshot open for a moment
            time.sleep(0.5)
    tmp.unlink(missing_ok=True)
    return False


def snapshot_path() -> Path:
    if not SNAPSHOT_PATH.exists():
        publish_snapshot()
    return SNAPSHOT_PATH if SNAPSHOT_PATH.exists() else WAREHOUSE_PATH


if __name__ == "__main__":
    print("published" if publish_snapshot() else "not published (warehouse busy or missing)")
