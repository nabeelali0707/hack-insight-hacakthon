"""Cross-platform stand-in for `make` (Windows has no make by default). Same targets:

    python run.py data | data-fast | quality | model | optimize | forecast | agent | golden
                  flow | serve | export-runs | test | all
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

TARGETS = {
    "data": [["bijlicast.cli", "data"]],
    "data-fast": [["bijlicast.cli", "data", "--keep-raw"]],
    "quality": [["bijlicast.cli", "quality"]],
    "model": [["bijlicast.model.train"], ["bijlicast.model.report"]],
    "optimize": [["bijlicast.model.optimize"]],
    "forecast": [["bijlicast.model.forecast"], ["bijlicast.insight.costlens"], ["bijlicast.quality.drift"]],
    "agent": [["bijlicast.insight.index"], ["bijlicast.insight.evaluate"]],
    "golden": [["bijlicast.insight.evaluate"]],
    "flow": [["bijlicast.pipeline.flow", "run"]],
    "serve": [["bijlicast.pipeline.flow", "serve"]],
    "export-runs": [["bijlicast.pipeline.flow", "export"]],
    "publish": [["bijlicast.publish", "proposal"], ["bijlicast.publish", "summary"]],
    "test": [["pytest", "-q", "tests"]],
}
TARGETS["all"] = TARGETS["data"] + TARGETS["model"] + TARGETS["forecast"] + TARGETS["agent"]

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data"
    if target not in TARGETS:
        raise SystemExit(f"unknown target {target!r}; choose from {', '.join(TARGETS)}")
    for cmd in TARGETS[target]:
        rc = subprocess.call([sys.executable, "-m", *cmd, *sys.argv[2:]], cwd=ROOT, env=ENV)
        if rc:
            raise SystemExit(rc)
