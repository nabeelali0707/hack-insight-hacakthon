"""Assemble the Hugging Face Space bundle and (optionally) upload it.

    python deploy/publish_space.py --assemble-only            # build/hf_space_bundle/
    python deploy/publish_space.py --repo <user>/bijlicast    # assemble + create Space + upload

Uploading uses the token stored by `hf auth login` (run by the account owner); this script
never reads or prints the token.

The bundle ships the prebuilt warehouse, raw files (SHA-verified by the manifest), document
index and trained model, so the Space starts instantly; its hourly refresher then fetches only
the new live weather snapshot and rebuilds gold, forecasts and briefs on its own.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BUNDLE = ROOT / "build" / "hf_space_bundle"


def _copy(src: Path, dst: Path, patterns=("*",)) -> int:
    n = 0
    for pat in patterns:
        for p in src.rglob(pat) if src.is_dir() else [src]:
            if p.is_file() and "__pycache__" not in p.parts:
                target = dst / p.relative_to(src.parent if not src.is_dir() else src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
                n += 1
    return n


def _warehouse_copy(dst: Path, retries: int = 20) -> None:
    import duckdb
    from bijlicast.config import WAREHOUSE_PATH
    for _ in range(retries):
        try:
            con = duckdb.connect(str(WAREHOUSE_PATH))
            con.execute("CHECKPOINT")
            con.close()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(WAREHOUSE_PATH, dst)
            return
        except duckdb.Error:  # hourly pipeline is writing; wait for it
            time.sleep(15)
    raise SystemExit("Warehouse is busy (pipeline running?) - try again in a minute.")


def assemble() -> Path:
    shutil.rmtree(BUNDLE, ignore_errors=True)
    BUNDLE.mkdir(parents=True)
    counts = {}
    for name in ("src", "web", "config"):
        counts[name] = _copy(ROOT / name, BUNDLE / name)
    counts["docs"] = _copy(ROOT / "docs", BUNDLE / "docs", ("*.pdf", "*.md"))
    counts["reports"] = _copy(ROOT / "reports", BUNDLE / "reports", ("*.png", "*.md", "*.csv"))
    counts["models"] = _copy(ROOT / "models", BUNDLE / "models", ("*.joblib", "*.json"))
    counts["raw"] = _copy(ROOT / "data" / "raw", BUNDLE / "data" / "raw")
    counts["index"] = _copy(ROOT / "data" / "index", BUNDLE / "data" / "index")
    _warehouse_copy(BUNDLE / "data" / "warehouse.duckdb")
    for f in ("manifest.csv", "AI_Use_Log.md"):
        shutil.copy2(ROOT / f, BUNDLE / f)
    for f in (ROOT / "deploy" / "hf_space").iterdir():
        shutil.copy2(f, BUNDLE / f.name)
    size = sum(p.stat().st_size for p in BUNDLE.rglob("*") if p.is_file()) / 1e6
    print(f"bundle: {BUNDLE}  ({size:.0f} MB)  files: {counts}")
    return BUNDLE


def upload(repo_id: str) -> None:
    from huggingface_hub import HfApi
    api = HfApi()
    who = api.whoami()["name"]  # fails clearly if `hf auth login` was not run
    print(f"logged in to Hugging Face as {who}")
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    api.upload_folder(folder_path=str(BUNDLE), repo_id=repo_id, repo_type="space",
                      commit_message="Deploy BijliCast dashboard + hourly refresher",
                      delete_patterns=["src/**", "web/**"])
    print(f"uploaded -> https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="<hf-username>/<space-name>")
    ap.add_argument("--assemble-only", action="store_true")
    a = ap.parse_args()
    assemble()
    if a.repo and not a.assemble_only:
        upload(a.repo)
