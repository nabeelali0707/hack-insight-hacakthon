"""Command line entry points (used by the Makefile and the Prefect flow).

    python -m bijlicast.cli data         # rebuild raw -> cleaned -> gold from an empty folder
    python -m bijlicast.cli data --keep-raw
    python -m bijlicast.cli quality      # print the latest quality status
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from .config import CLEANED_DIR, DATA_DIR, PROCESSED_DIR, RAW_DIR, WAREHOUSE_PATH


def cmd_data(args) -> int:
    from . import manifest as mf
    from .warehouse import build

    if args.keep_raw:
        for p in (CLEANED_DIR, PROCESSED_DIR):
            shutil.rmtree(p, ignore_errors=True)
        WAREHOUSE_PATH.unlink(missing_ok=True)
    else:
        # Start from an empty working folder: everything under data/ is rebuilt.
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    known = len(mf.load())
    summary = build(fetch=True, include_forecast=not args.no_forecast)
    st = summary["status"]
    print("\n=== make data summary ===")
    print(f"run_id           : {summary['run_id']}")
    print(f"manifest         : {known} files previously recorded -> fetch statuses {summary['fetch']}")
    for k, v in summary["counts"].items():
        print(f"  {k:<32}{v:>10,}")
    print(f"quality          : {st['overall']}  (FIX {st['n_fix']}, FILL {st['n_fill']}, FLAG {st['n_flag']}, "
          f"PASS {st['n_pass']}, critical {st['n_critical']}, pending review {st['n_pending_review']})")
    print(f"freshness        : ISMO latest {st['ismo_latest_period']} ({st['ismo_age_days']} days), "
          f"live weather {st.get('live_age_hours', 'n/a')} h old")
    print(f"timings (s)      : {summary['timings']}")
    changed_immutable = summary["fetch"].get("changed", 0)
    if args.strict and changed_immutable:
        print("STRICT: raw files changed versus manifest.csv", file=sys.stderr)
        return 2
    return 0


def cmd_quality(_args) -> int:
    from .warehouse import connect

    con = connect(read_only=True)
    print(json.dumps(con.execute("SELECT * FROM quality.status").df().to_dict("records")[0], indent=1, default=str))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bijlicast")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("data", help="rebuild the warehouse from source")
    d.add_argument("--keep-raw", action="store_true", help="reuse raw files already on disk (SHA-256 verified)")
    d.add_argument("--no-forecast", action="store_true", help="skip the live weather snapshot")
    d.add_argument("--strict", action="store_true", help="fail if a raw file's SHA-256 changed")
    d.set_defaults(func=cmd_data)
    q = sub.add_parser("quality", help="print latest quality status")
    q.set_defaults(func=cmd_quality)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
