"""Paths and the source registry, shared by every pipeline step."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"
MANIFEST_PATH = ROOT / "manifest.csv"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"
KNOWLEDGE_DIR = ROOT / "knowledge"

PKT_OFFSET_HOURS = 5  # Pakistan Standard Time = UTC+5, no daylight saving

# Entities in the order ISMO lists them; KE is the primary user's utility.
ENTITY_ORDER = ["KE", "LESCO", "FESCO", "GEPCO", "IESCO", "MEPCO", "PESCO", "QESCO", "HESCO", "SEPCO"]

# ISMO sometimes writes "K-Electric", "KE", "K Electric"; map every spelling to one code.
ENTITY_ALIASES = {
    "K-ELECTRIC": "KE", "K ELECTRIC": "KE", "KE": "KE", "KESC": "KE",
    "LESCO": "LESCO", "FESCO": "FESCO", "GEPCO": "GEPCO", "IESCO": "IESCO",
    "MEPCO": "MEPCO", "PESCO": "PESCO", "QESCO": "QESCO", "HESCO": "HESCO",
    "SEPCO": "SEPCO", "TESCO": "TESCO",
}


@lru_cache(maxsize=1)
def sources() -> dict:
    """Load config/sources.yaml once."""
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def entities() -> dict[str, dict]:
    """Entity code -> metadata (name, city, province, lat, lon)."""
    return sources()["open_meteo"]["entities"]


def ensure_dirs() -> None:
    for d in (RAW_DIR, CLEANED_DIR, PROCESSED_DIR, INDEX_DIR, MODELS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
