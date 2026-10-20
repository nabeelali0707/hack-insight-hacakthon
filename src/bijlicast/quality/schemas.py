"""Pandera schemas: the validation *tools* the Data Quality Agent runs on cleaned tables."""

from __future__ import annotations

from pandera.errors import SchemaErrors
from pandera.pandas import Check, Column, DataFrameSchema

from ..config import ENTITY_ORDER

profile_schema = DataFrameSchema(
    {
        "entity": Column(str, Check.isin(ENTITY_ORDER)),
        "period": Column("datetime64[ns]"),
        "hour": Column(int, Check.in_range(0, 23)),
        # A DISCO's average hourly demand: positive, below 15 GW (whole system peaks ~30 GW).
        "demand_mw": Column(float, [Check.gt(0), Check.lt(15_000)]),
    },
    unique=["entity", "period", "hour"],
    coerce=True,
)

energy_schema = DataFrameSchema(
    {
        "entity": Column(str, Check.isin(ENTITY_ORDER)),
        "period": Column("datetime64[ns]"),
        "avg_daily_mwh": Column(float, [Check.gt(0), Check.lt(400_000)]),
    },
    unique=["entity", "period"],
    coerce=True,
)

price_schema = DataFrameSchema(
    {
        "ts_utc": Column("datetime64[ns, UTC]", unique=True),
        "hour_pkt": Column(int, Check.in_range(0, 23)),
        "price_rs_kwh": Column(float, Check.ge(0), nullable=True),
    },
    coerce=True,
)

weather_schema = DataFrameSchema(
    {
        "entity": Column(str, Check.isin(ENTITY_ORDER)),
        "ts_utc": Column("datetime64[ns, UTC]"),
        "temp_c": Column(float, Check.in_range(-40, 60), nullable=True),
        "rh_pct": Column(float, Check.in_range(0, 100), nullable=True),
        "dewpoint_c": Column(float, Check.in_range(-60, 40), nullable=True),
        "apparent_c": Column(float, Check.in_range(-50, 75), nullable=True),
        "precip_mm": Column(float, Check.ge(0), nullable=True),
        "cloud_pct": Column(float, Check.in_range(0, 100), nullable=True),
        "wind_kmh": Column(float, Check.in_range(0, 250), nullable=True),
        "swrad_wm2": Column(float, Check.in_range(0, 1400), nullable=True),
    },
    unique=["entity", "ts_utc"],
    coerce=True,
)


def run_schema(schema: DataFrameSchema, df) -> list[dict]:
    """Validate lazily and return failure cases as plain dicts (empty list = pass)."""
    try:
        schema.validate(df, lazy=True)
        return []
    except SchemaErrors as err:
        fc = err.failure_cases
        return fc[["column", "check", "failure_case", "index"]].astype(str).to_dict("records")
