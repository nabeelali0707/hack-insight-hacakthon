"""Parse raw files into *staging* DataFrames. No cleaning decisions are made here:
the parsers only read what the publisher wrote and attach provenance (file_id, sheet).
Every correction happens later, in the Data Quality Agent, where it is logged.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import openpyxl
import pandas as pd

from .config import ENTITY_ALIASES, ROOT

HOUR_COL = re.compile(r"^\s*hour\s*(\d{1,2})\s*$", re.I)


def _entity(label) -> str | None:
    if label is None:
        return None
    key = re.sub(r"\s+", " ", str(label)).strip().upper()
    return ENTITY_ALIASES.get(key)


def _rows(ws) -> list[tuple]:
    return [r for r in ws.iter_rows(values_only=True)]


def parse_ismo_workbook(path: Path, file_id: str, period: str) -> dict[str, pd.DataFrame]:
    """Return staging tables found in one ISMO monthly workbook.

    Keys (present only if the sheet exists):
      profile   - entity, hour, demand_mw, sheet          (KE-Demand + DISCOs Demand)
      energy    - entity, avg_mwh, total_energy_gwh, share, avg_label, days_reported
      national  - hour, national_demand_mw, marginal_cost
      genmix    - fuel, hour, generation_mw
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict[str, pd.DataFrame] = {}
    sheets = {ws.title.strip().lower(): ws for ws in wb.worksheets}

    profile_rows = []
    if "ke-demand" in sheets:
        for r in _rows(sheets["ke-demand"])[1:]:
            if r and isinstance(r[0], (int, float)) and r[1] is not None:
                profile_rows.append(("KE", int(r[0]), r[1], "KE-Demand"))
    if "discos demand" in sheets:
        rows = _rows(sheets["discos demand"])
        header = rows[0]
        hour_idx = {i: int(m.group(1)) for i, h in enumerate(header) if h and (m := HOUR_COL.match(str(h)))}
        for r in rows[1:]:
            ent = _entity(r[0]) if r else None
            if ent is None:
                continue  # unlabeled total rows are recomputed, never trusted
            for i, h in hour_idx.items():
                if i < len(r) and r[i] is not None:
                    profile_rows.append((ent, h, r[i], "DISCOs Demand"))
    if profile_rows:
        out["profile"] = pd.DataFrame(profile_rows, columns=["entity", "hour", "demand_mw", "sheet"])

    if "disco consumption" in sheets:
        rows = _rows(sheets["disco consumption"])
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        days_reported = None
        recs = []
        for i, r in enumerate(rows[1:], start=1):
            if r and str(r[0]).strip().lower() == "month" and i + 1 < len(rows):
                nxt = rows[i + 1]
                days_reported = nxt[1] if len(nxt) > 1 else None
            ent = _entity(r[0]) if r else None
            if ent is None:
                continue
            recs.append((ent, r[1], r[2], r[3] if len(r) > 3 else None))
        if recs:
            df = pd.DataFrame(recs, columns=["entity", "avg_mwh", "total_energy_gwh", "share"])
            df["avg_label"] = header[1] if len(header) > 1 else ""
            df["days_reported"] = days_reported
            out["energy"] = df

    if "marginal cost - demand" in sheets:
        recs = [(int(r[0]), r[1], r[2]) for r in _rows(sheets["marginal cost - demand"])[1:]
                if r and isinstance(r[0], (int, float)) and r[1] is not None]
        if recs:
            out["national"] = pd.DataFrame(recs, columns=["hour", "national_demand_mw", "marginal_cost"])

    if "generation mix" in sheets:
        rows = _rows(sheets["generation mix"])
        header = rows[0]
        hour_idx = {i: int(m.group(1)) for i, h in enumerate(header) if h and (m := HOUR_COL.match(str(h)))}
        recs = []
        for r in rows[1:]:
            if not r or r[0] is None:
                continue
            for i, h in hour_idx.items():
                if i < len(r) and isinstance(r[i], (int, float)):
                    recs.append((str(r[0]).strip(), h, float(r[i])))
        if recs:
            out["genmix"] = pd.DataFrame(recs, columns=["fuel", "hour", "generation_mw"])

    for df in out.values():
        df.insert(0, "file_id", file_id)
        df.insert(1, "period", period)
    return out


def parse_ismo_price(path: Path, file_id: str) -> pd.DataFrame:
    """Hourly marginal price workbook: Date (PKT calendar day), Hour (0-23 PKT), price (Rs/kWh)."""
    df = pd.read_excel(path, sheet_name=0, usecols=[0, 1, 2], engine="openpyxl")
    df.columns = ["date_pkt", "hour_pkt", "price_rs_kwh"]
    df = df.dropna(how="all")
    df.insert(0, "file_id", file_id)
    return df


def parse_open_meteo_csv(path: Path, file_id: str, entity: str) -> pd.DataFrame:
    """Open-Meteo CSV: two metadata lines, a blank line, then the hourly table (timezone GMT)."""
    text = path.read_text(encoding="utf-8")
    meta_block, _, table = text.partition("\n\n")
    meta = pd.read_csv(io.StringIO(meta_block))
    if int(meta.loc[0, "utc_offset_seconds"]) != 0:
        raise ValueError(f"{path} is not in UTC")
    df = pd.read_csv(io.StringIO(table))
    df.columns = [re.sub(r"\s*\(.*\)$", "", c).strip() for c in df.columns]
    df = df.rename(columns={
        "time": "ts_utc", "temperature_2m": "temp_c", "relative_humidity_2m": "rh_pct",
        "dew_point_2m": "dewpoint_c", "apparent_temperature": "apparent_c",
        "precipitation": "precip_mm", "cloud_cover": "cloud_pct",
        "wind_speed_10m": "wind_kmh", "shortwave_radiation": "swrad_wm2",
    })
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df.insert(0, "entity", entity)
    df.insert(0, "file_id", file_id)
    df["grid_lat"] = float(meta.loc[0, "latitude"])
    df["grid_lon"] = float(meta.loc[0, "longitude"])
    return df


def local(path_str: str) -> Path:
    return ROOT / path_str
