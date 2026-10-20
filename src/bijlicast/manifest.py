"""manifest.csv: one row per raw file (source, query, fetch time, SHA-256, licence).

Raw files are evidence. `make data` re-fetches them and checks the SHA-256 against
the committed manifest:

* immutable sources (ISMO uploads): a mismatch is an error, because the publisher
  changed a file we already used;
* revisable sources (weather reanalysis and forecasts): a mismatch is recorded as a new
  version and reported, because ERA5T values are revised and forecasts update.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import MANIFEST_PATH, ROOT


@dataclass
class ManifestEntry:
    file_id: str          # stable key, e.g. ismo_disco_2024-02_lNeqTbtM6D
    source: str           # ismo_disco_monthly | ismo_hourly_price | open_meteo_archive | open_meteo_forecast | document
    title: str
    period: str
    query: str            # URL actually requested (with parameters)
    local_path: str       # relative to repo root
    fetched_at_utc: str
    sha256: str
    bytes: int
    licence: str
    immutable: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load() -> dict[str, ManifestEntry]:
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        r["bytes"] = int(r["bytes"])
        r["immutable"] = str(r["immutable"]).lower() == "true"
        out[r["file_id"]] = ManifestEntry(**r)
    return out


def save(entries: dict[str, ManifestEntry]) -> None:
    names = [f.name for f in fields(ManifestEntry)]
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=names, lineterminator="\n")
        w.writeheader()
        for key in sorted(entries):
            w.writerow(asdict(entries[key]))


def relpath(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()
