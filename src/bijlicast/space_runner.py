"""Hourly refresher for the Hugging Face Space (no Prefect server there).

Runs the same Supervisor pipeline as the local Prefect flow: once shortly after start-up,
then at five minutes past every hour. Each run is recorded in ops.pipeline_runs and the
serving snapshot is republished, so the dashboard's freshness / quality / last-successful-run
panels stay live even when the team's own machine is off.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timedelta, timezone

from .pipeline.supervisor import run_once


def _seconds_to_next_run(minute: int = 5) -> float:
    now = datetime.now(timezone.utc)
    nxt = now.replace(minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(hours=1)
    return (nxt - now).total_seconds()


def main(first_delay: int = 90) -> None:
    time.sleep(first_delay)  # let the web server come up first
    while True:
        try:
            rec = run_once()
            print(f"[space-runner] {rec['run_id']}: {rec['status']} ({rec.get('quality')}) {rec['timings']}", flush=True)
        except Exception:  # a failed run is recorded by the supervisor; keep the loop alive
            print("[space-runner] run failed:\n" + traceback.format_exc()[-1500:], flush=True)
        time.sleep(_seconds_to_next_run())


if __name__ == "__main__":
    main()
