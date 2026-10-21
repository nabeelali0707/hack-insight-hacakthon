"""Prefect flow: the Supervisor's steps as tasks, scheduled at five minutes past every hour.

    python -m bijlicast.pipeline.flow run        # one run now
    python -m bijlicast.pipeline.flow serve      # long-running: schedule "5 * * * *"
    python -m bijlicast.pipeline.flow export     # write reports/prefect_runs.csv (unedited API export)

Retries are set per task; a failed run never corrupts gold (quality gate + last-good gold).
"""

from __future__ import annotations

import sys

from prefect import flow, task

from . import supervisor as sup


@task(name="fetch-and-build (quality gate)", retries=2, retry_delay_seconds=120)
def t_fetch_build(run_id: str) -> dict:
    return sup.step_fetch_and_build(run_id)


@task(name="drift-monitor", retries=1, retry_delay_seconds=30)
def t_drift() -> dict:
    return sup.step_drift()


@task(name="forecast-and-cost-lens", retries=1, retry_delay_seconds=30)
def t_forecast() -> dict:
    return sup.step_forecast_and_cost()


@task(name="insight-briefs-and-golden-eval", retries=1, retry_delay_seconds=30)
def t_insight() -> dict:
    return sup.step_insight()


@flow(name="bijlicast-hourly", log_prints=True)
def bijlicast_hourly() -> dict:
    steps = {"fetch_build": t_fetch_build, "drift": t_drift, "forecast": t_forecast, "insight": t_insight}
    rec = sup.run_once(steps=steps)
    print(f"run {rec['run_id']}: {rec['status']} | quality {rec.get('quality')} | timings {rec['timings']} "
          f"| decisions {rec['decisions']}")
    return rec


def export_runs(path: str = "reports/prefect_runs.csv") -> int:
    """Export flow-run history from the Prefect API exactly as stored (no editing)."""
    import asyncio
    import csv

    from prefect.client.orchestration import get_client
    from prefect.client.schemas.filters import FlowFilter, FlowFilterName
    from prefect.client.schemas.sorting import FlowRunSort

    async def _get():
        async with get_client() as client:
            return await client.read_flow_runs(flow_filter=FlowFilter(name=FlowFilterName(any_=["bijlicast-hourly"])),
                                               sort=FlowRunSort.START_TIME_ASC, limit=200)

    runs = asyncio.run(_get())
    cols = ["id", "name", "state_type", "state_name", "expected_start_time", "start_time", "end_time",
            "total_run_time", "run_count", "deployment_id"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in runs:
            w.writerow([r.id, r.name, r.state_type.value if r.state_type else "", r.state_name,
                        r.expected_start_time, r.start_time, r.end_time, r.total_run_time, r.run_count,
                        r.deployment_id])
    return len(runs)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "serve":
        # limit=1: never two runs at once (e.g. late runs after the laptop wakes) - DuckDB has one writer
        bijlicast_hourly.serve(name="hourly", cron="5 * * * *", tags=["hackinsight", "bijlicast"], limit=1)
    elif cmd == "export":
        print(f"exported {export_runs()} runs to reports/prefect_runs.csv")
    else:
        bijlicast_hourly()
