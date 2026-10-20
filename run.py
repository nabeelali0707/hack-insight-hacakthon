"""Cross-platform stand-in for `make` (Windows has no make by default).

    python run.py data | data-fast | quality | model | agent | flow | test
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

TARGETS = {
    "data": ["data"],
    "data-fast": ["data", "--keep-raw"],
    "quality": ["quality"],
}

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data"
    if target == "test":
        raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT,
                                         env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}))
    from bijlicast.cli import main
    raise SystemExit(main(TARGETS.get(target, [target]) + sys.argv[2:]))
