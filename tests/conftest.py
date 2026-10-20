import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _warehouse_ready() -> bool:
    return (ROOT / "data" / "warehouse.duckdb").exists()


def _index_ready() -> bool:
    return (ROOT / "data" / "index" / "chunks.parquet").exists()


needs_warehouse = pytest.mark.skipif(not _warehouse_ready(), reason="run `make data` first")
needs_index = pytest.mark.skipif(not (_warehouse_ready() and _index_ready()), reason="run `make data` and `make agent` first")
