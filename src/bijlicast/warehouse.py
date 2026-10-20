"""Build the warehouse: raw files -> staging -> Data Quality Agent -> cleaned -> gold.

DuckDB file: data/warehouse.duckdb, schemas:
  raw      manifest + fetch log (the raw *files* live in data/raw and are never edited)
  cleaned  typed, UTC, de-duplicated, flagged tables (every change made by code, logged)
  gold     analysis/model tables with stable, human-readable row IDs (every number shown comes from here)
  quality  quality_log (append-only), review_queue, status
  ops      pipeline runs
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import duckdb
import pandas as pd

from . import manifest as mf
from .config import CLEANED_DIR, PROCESSED_DIR, REPORTS_DIR, WAREHOUSE_PATH, ensure_dirs, entities
from .fetch import FetchResult, fetch_all, ismo_registry
from .parse import local, parse_ismo_price, parse_ismo_workbook, parse_open_meteo_csv
from .quality import DataQualityAgent

GOLD_TABLES = ["entity", "demand_profile", "monthly_energy", "price_hourly", "price_month_hour",
               "national_profile", "generation_mix", "weather_month_hour", "weather_live_hourly"]


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE_PATH), read_only=read_only)


def _write(con, schema: str, name: str, df: pd.DataFrame, parquet_dir=None) -> int:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {schema}.{name} AS SELECT * FROM _df")
    con.unregister("_df")
    if parquet_dir is not None:
        parquet_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY {schema}.{name} TO '{(parquet_dir / f'{name}.parquet').as_posix()}' (FORMAT parquet)")
    return len(df)


def _stage_ismo(entries: dict) -> tuple[list[dict], pd.DataFrame | None]:
    staged, price = [], None
    for item in ismo_registry():
        e = entries.get(item["file_id"])
        if e is None or not local(e.local_path).exists():
            continue
        if item["source"] == "ismo_disco_monthly":
            staged.append({"file_id": item["file_id"], "period": item["period"], "published": item["published"],
                           "title": item["title"],
                           "tables": parse_ismo_workbook(local(e.local_path), item["file_id"], item["period"])})
        else:
            price = parse_ismo_price(local(e.local_path), item["file_id"])
    return staged, price


def _stage_weather(entries: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp | None]:
    archive, live, live_stamp = [], [], None
    latest_live: dict[str, mf.ManifestEntry] = {}
    for e in entries.values():
        if e.source == "open_meteo_archive":
            ent = e.file_id.removeprefix("weather_archive_")
            archive.append(parse_open_meteo_csv(local(e.local_path), e.file_id, ent))
        elif e.source == "open_meteo_forecast" and local(e.local_path).exists():
            ent = e.file_id.split("_")[2]
            if ent not in latest_live or e.period > latest_live[ent].period:
                latest_live[ent] = e
    for ent, e in latest_live.items():
        df = parse_open_meteo_csv(local(e.local_path), e.file_id, ent)
        df["snapshot_utc"] = pd.Timestamp(datetime.strptime(e.period, "%Y%m%dT%H%MZ"), tz="UTC")
        live.append(df)
        stamp = df["snapshot_utc"].iloc[0]
        live_stamp = stamp if live_stamp is None or stamp > live_stamp else live_stamp
    return (pd.concat(archive, ignore_index=True),
            pd.concat(live, ignore_index=True) if live else pd.DataFrame(), live_stamp)


GOLD_SQL = {
    "demand_profile": """
        SELECT 'DP-' || p.entity || '-' || strftime(p.period, '%Y%m') || '-' || lpad(CAST(p.hour AS VARCHAR), 2, '0') AS row_id,
               p.entity, e.name AS entity_name, e.province, CAST(p.period AS DATE) AS period, p.hour AS hour_pkt,
               ROUND(p.demand_mw, 2) AS demand_mw, p.file_id AS source_file_id, p.dq_flags
        FROM cleaned.ismo_profile p JOIN gold.entity e ON e.code = p.entity
        WHERE NOT p.exclude ORDER BY p.entity, p.period, p.hour""",
    "monthly_energy": """
        SELECT 'ME-' || m.entity || '-' || strftime(m.period, '%Y%m') AS row_id, m.entity, e.name AS entity_name,
               e.province, CAST(m.period AS DATE) AS period, ROUND(m.avg_daily_mwh / 24, 2) AS avg_mw,
               ROUND(m.energy_daily_gwh, 3) AS energy_daily_gwh, ROUND(m.energy_month_gwh, 2) AS energy_month_gwh,
               m.share, m.file_id AS source_file_id, m.dq_flags
        FROM cleaned.ismo_energy m JOIN gold.entity e ON e.code = m.entity
        WHERE NOT m.exclude ORDER BY m.entity, m.period""",
    "price_hourly": """
        SELECT 'PX-' || strftime(date_pkt, '%Y%m%d') || '-' || lpad(CAST(hour_pkt AS VARCHAR), 2, '0') AS row_id,
               ts_utc, CAST(date_pkt AS DATE) AS date_pkt, hour_pkt, price_rs_kwh, file_id AS source_file_id, dq_flags
        FROM cleaned.price_hourly ORDER BY ts_utc""",
    "price_month_hour": """
        SELECT 'PM-' || strftime(date_trunc('month', date_pkt), '%Y%m') || '-' || lpad(CAST(hour_pkt AS VARCHAR), 2, '0') AS row_id,
               CAST(date_trunc('month', date_pkt) AS DATE) AS period, hour_pkt,
               ROUND(AVG(price_rs_kwh), 3) AS avg_price_rs_kwh, ROUND(MAX(price_rs_kwh), 3) AS max_price_rs_kwh,
               COUNT(price_rs_kwh) AS n_hours
        FROM cleaned.price_hourly GROUP BY 2, 3, 1 ORDER BY 2, 3""",
    "national_profile": """
        SELECT 'NP-' || strftime(period, '%Y%m') || '-' || lpad(CAST(hour AS VARCHAR), 2, '0') AS row_id,
               CAST(period AS DATE) AS period, hour AS hour_pkt, ROUND(national_demand_mw, 1) AS national_demand_mw,
               ROUND(marginal_cost, 3) AS marginal_cost_rs_kwh, file_id AS source_file_id
        FROM cleaned.ismo_national ORDER BY period, hour""",
    "generation_mix": """
        SELECT 'GM-' || strftime(period, '%Y%m') || '-' || lpad(CAST(hour AS VARCHAR), 2, '0') || '-' || upper(fuel) AS row_id,
               CAST(period AS DATE) AS period, hour AS hour_pkt, fuel, ROUND(generation_mw, 1) AS generation_mw,
               file_id AS source_file_id
        FROM cleaned.ismo_genmix ORDER BY period, hour, fuel""",
    "weather_month_hour": """
        WITH w AS (SELECT entity, ts_utc + INTERVAL 5 HOUR AS ts_pkt, * EXCLUDE (entity) FROM cleaned.weather_hourly)
        SELECT 'WX-' || entity || '-' || strftime(date_trunc('month', ts_pkt), '%Y%m') || '-' || lpad(CAST(hour(ts_pkt) AS VARCHAR), 2, '0') AS row_id,
               entity, CAST(date_trunc('month', ts_pkt) AS DATE) AS period, hour(ts_pkt) AS hour_pkt,
               ROUND(AVG(temp_c), 2) AS temp_c, ROUND(AVG(apparent_c), 2) AS apparent_c, ROUND(AVG(rh_pct), 1) AS rh_pct,
               ROUND(AVG(dewpoint_c), 2) AS dewpoint_c, ROUND(AVG(swrad_wm2), 1) AS swrad_wm2,
               ROUND(AVG(cloud_pct), 1) AS cloud_pct, ROUND(AVG(precip_mm), 3) AS precip_mm, ROUND(AVG(wind_kmh), 2) AS wind_kmh,
               ROUND(AVG(GREATEST(temp_c - 24, 0)), 3) AS cdh24, ROUND(AVG(GREATEST(18 - temp_c, 0)), 3) AS hdh18,
               ROUND(MAX(temp_c), 2) AS temp_max_c, COUNT(*) AS n_hours, SUM(CAST(is_filled AS INT)) AS n_filled
        FROM w GROUP BY ALL ORDER BY entity, period, hour_pkt""",
    "weather_live_hourly": """
        SELECT 'WL-' || entity || '-' || strftime(ts_utc + INTERVAL 5 HOUR, '%Y%m%d%H') AS row_id, entity, ts_utc,
               ts_utc + INTERVAL 5 HOUR AS ts_pkt, temp_c, apparent_c, rh_pct, dewpoint_c, swrad_wm2, cloud_pct,
               precip_mm, wind_kmh, is_filled, snapshot_utc, file_id AS source_file_id
        FROM cleaned.weather_live ORDER BY entity, ts_utc""",
}


def build(run_id: str | None = None, fetch: bool = True, include_forecast: bool = True,
          fetch_results: list[FetchResult] | None = None) -> dict:
    t0 = time.time()
    run_id = run_id or datetime.now(timezone.utc).strftime("run%Y%m%dT%H%M%SZ")
    ensure_dirs()
    timings = {}

    t = time.time()
    results = fetch_all(include_forecast=include_forecast) if fetch else (fetch_results or [])
    timings["fetch_s"] = round(time.time() - t, 2)
    entries = mf.load()

    agent = DataQualityAgent(run_id)
    agent.review_fetch(results)

    t = time.time()
    staged, price_raw = _stage_ismo(entries)
    ismo = agent.review_ismo(staged)
    price = agent.review_price(price_raw)
    wx_raw, live_raw, live_stamp = _stage_weather(entries)
    wx = agent.review_weather(wx_raw, "weather_hourly")
    live = pd.DataFrame()
    if not live_raw.empty:
        snap = live_raw.groupby("entity")["snapshot_utc"].first()
        live = agent.review_weather(live_raw.drop(columns=["snapshot_utc"]), "weather_live")
        live["snapshot_utc"] = live["entity"].map(snap)
    latest_period = ismo["profile"]["period"].max()
    freshness = agent.review_freshness(latest_period, live_stamp)
    timings["quality_agent_s"] = round(time.time() - t, 2)

    # Gate 2 (quality) runs BEFORE anything is published: a critical finding quarantines this build
    agent.review_documents(entries)
    log = agent.log_frame()
    status = {
        "run_id": run_id, "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_fix": int((log.action == "FIX").sum()), "n_fill": int((log.action == "FILL").sum()),
        "n_flag": int((log.action == "FLAG").sum()), "n_pass": int((log.action == "PASS").sum()),
        "n_critical": int((log.severity == "critical").sum()),
        "n_pending_review": int(log["needs_review"].sum()),
        **freshness,
    }
    status["overall"] = "RED" if status["n_critical"] else ("AMBER" if status["n_flag"] else "GREEN")
    publish = status["overall"] != "RED"
    status["published"] = publish
    target_clean, target_gold = ("cleaned", "gold") if publish else ("quarantine", "quarantine")

    t = time.time()
    con = connect()
    counts = {}
    # raw layer bookkeeping
    man = pd.DataFrame([vars(e) for e in entries.values()])
    _write(con, "raw", "manifest", man)
    fetch_log = pd.DataFrame([{"run_id": run_id, **vars(r)} for r in results]) if results else pd.DataFrame(
        columns=["run_id", "file_id", "status", "detail"])
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.register("_f", fetch_log)
    con.execute("CREATE TABLE IF NOT EXISTS raw.fetch_log AS SELECT * FROM _f WHERE 1=0")
    con.execute("INSERT INTO raw.fetch_log SELECT * FROM _f")
    con.unregister("_f")

    # cleaned layer (or quarantine if the gate failed)
    cdir = CLEANED_DIR if publish else None
    for name, df in (("ismo_profile", ismo["profile"]), ("ismo_energy", ismo["energy"]),
                     ("ismo_national", ismo["national"]), ("ismo_genmix", ismo["genmix"]),
                     ("price_hourly", price), ("weather_hourly", wx), ("weather_live", live)):
        if name == "weather_live" and live.empty:
            continue
        qname = name if publish else f"clean_{name}"
        counts[f"{target_clean}.{qname}"] = _write(con, target_clean, qname, df, cdir)

    # gold layer: only when the gate passed - otherwise gold keeps the last good version
    if publish:
        ent = pd.DataFrame([{"code": k, **v} for k, v in entities().items()])
        counts["gold.entity"] = _write(con, "gold", "entity", ent, PROCESSED_DIR)
        for name, sql in GOLD_SQL.items():
            if name == "weather_live_hourly" and live.empty:
                continue
            counts[f"gold.{name}"] = _write(con, "gold", name, con.execute(sql).df(), PROCESSED_DIR)
    timings["warehouse_s"] = round(time.time() - t, 2)

    # quality log (append-only) + review queue + status
    con.execute("CREATE SCHEMA IF NOT EXISTS quality")
    con.register("_l", log)
    con.execute("CREATE TABLE IF NOT EXISTS quality.quality_log AS SELECT * FROM _l WHERE 1=0")
    con.execute("INSERT INTO quality.quality_log SELECT * FROM _l")
    con.unregister("_l")
    queue = log[log["needs_review"]]
    _write(con, "quality", "review_queue", queue)
    _write(con, "quality", "status", pd.DataFrame([status]))
    con.close()

    log.to_csv(REPORTS_DIR / "quality_log_latest.csv", index=False)
    timings["total_s"] = round(time.time() - t0, 2)
    return {"run_id": run_id, "counts": counts, "status": status, "timings": timings,
            "fetch": {s: sum(r.status == s for r in results) for s in {r.status for r in results}}}
