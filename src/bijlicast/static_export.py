"""Static export of the dashboard for a free Hugging Face *static* Space.

Every JSON file is produced by calling the real API endpoints in-process (FastAPI TestClient),
so the static site shows exactly what the live server shows. The Insight Agent answers a set
of prepared questions (English + Urdu); the static page labels them as prepared answers.

    python -m bijlicast.static_export            # build/hf_static/
    python -m bijlicast.static_export --push     # + upload data/ to the configured Space

The hourly Supervisor calls publish_hourly() so the public page refreshes with each run.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import CONFIG_DIR, DOCS_DIR, REPORTS_DIR, ROOT

OUT = ROOT / "build" / "hf_static"
WEB = ROOT / "web"

# (question, lang, context entity, featured in the suggestion chips)
PREPARED = [
    ("What is K-Electric's expected demand next month?", "en", "KE", True),
    ("Compare next month with last year", "en", "KE", True),
    ("What is K-Electric's expected demand this month?", "en", "KE", False),
    ("How much would K-Electric save by shifting peak demand?", "en", "KE", True),
    ("What are K-Electric's peak hours?", "en", "KE", True),
    ("How accurate is the model for K-Electric compared with the baseline?", "en", "KE", True),
    ("Which data was flagged as copied by the quality agent?", "en", "KE", True),
    ("Is there any model drift for K-Electric?", "en", "KE", True),
    ("What was K-Electric's demand in September 2026?", "en", "KE", True),
    ("Why did K-Electric's demand fall in October 2025?", "en", "KE", False),
    ("What does NEPRA say about transmission and distribution losses in KE?", "en", "KE", False),
    ("What will K-Electric's demand be in December 2027?", "en", "KE", False),
    ("What is the electricity demand in Gilgit next month?", "en", "KE", False),
    ("اگلے مہینے کراچی میں بجلی کی متوقع طلب کتنی ہے؟", "ur", "KE", True),
    ("کے الیکٹرک پیک اوقات سے طلب منتقل کر کے کتنی بچت کر سکتا ہے؟", "ur", "KE", True),
    ("لاہور میں اگلے مہینے بجلی کی متوقع طلب کتنی ہے؟", "ur", "LESCO", True),
    ("کے الیکٹرک کے لیے ماڈل کتنا درست ہے؟", "ur", "KE", True),
] + [
    (f"What is {e}'s expected demand next month?", "en", e, False)
    for e in ("LESCO", "FESCO", "GEPCO", "IESCO", "MEPCO", "PESCO", "QESCO", "HESCO", "SEPCO")
] + [
    (f"How accurate is the model for {e}?", "en", e, False)
    for e in ("LESCO", "FESCO", "GEPCO", "IESCO", "MEPCO", "PESCO", "QESCO", "HESCO", "SEPCO")
]

SPACE_CARD = """---
title: BijliCast
emoji: ⚡
colorFrom: blue
colorTo: indigo
sdk: static
app_file: index.html
pinned: false
short_description: Hourly demand outlook for K-Electric and Pakistan's DISCOs
---
"""


def deploy_config() -> dict:
    p = CONFIG_DIR / "deploy.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(rel: str, obj) -> None:
    p = OUT / "data" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export_data(with_answers: bool = True) -> dict:
    from fastapi.testclient import TestClient

    from .api import app
    client = TestClient(app)

    def get(url):
        r = client.get(url)
        r.raise_for_status()
        return r.json()

    shutil.rmtree(OUT / "data", ignore_errors=True)
    meta = get("/api/meta")
    _save("meta.json", meta)
    ents, months = [e["code"] for e in meta["entities"]], meta["forecast_months"]
    n = 1
    for m in months:
        _save(f"forecasts/{m}.json", get(f"/api/forecasts?month={m}")); n += 1
    for e in ents:
        for m in months:
            _save(f"workspace/{e}_{m}.json", get(f"/api/workspace?entity={e}&month={m}"))
            _save(f"history/{e}_{m}.json", get(f"/api/forecast_history?entity={e}&month={m}")); n += 2
        cost = get(f"/api/cost?entity={e}")
        _save(f"cost/{e}_latest.json", cost); n += 1
        for p in cost.get("periods", []):
            _save(f"cost/{e}_{p}.json", get(f"/api/cost?entity={e}&period={p}")); n += 1
        _save(f"performance/{e}.json", get(f"/api/performance?entity={e}"))
        _save(f"confidence/{e}.json", get(f"/api/confidence?entity={e}")); n += 2
    for name, url in (("quality.json", "/api/quality"), ("runs.json", "/api/runs"), ("sources.json", "/api/sources")):
        _save(name, get(url)); n += 1
    for lang in ("en", "ur"):
        _save(f"briefs_{lang}.json", get(f"/api/briefs?lang={lang}")); n += 1
    if with_answers:
        answers = []
        for q, lang, ent, featured in PREPARED:
            r = client.post("/api/ask", json={"question": q, "lang": lang, "entity": ent})
            r.raise_for_status()
            answers.append({**r.json(), "featured": featured})
        _save("prepared_answers.json", {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "answers": answers})
        n += 1
    return {"files": n, "snapshot_utc": meta["snapshot_utc"]}


def export_site() -> Path:
    """Static shell: web app (flagged static), documents and figures, Space card."""
    OUT.mkdir(parents=True, exist_ok=True)
    for p in WEB.rglob("*"):
        if p.is_file():
            dst = OUT / p.relative_to(WEB)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script type="module" src="js/app.js"></script>',
                        '<script>window.BIJLICAST_STATIC = true;</script>\n  <script type="module" src="js/app.js"></script>')
    (OUT / "index.html").write_text(html, encoding="utf-8")
    for pat in ("*.pdf", "*.md"):
        for p in DOCS_DIR.glob(pat):
            (OUT / "files" / "docs").mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, OUT / "files" / "docs" / p.name)
    for p in list(REPORTS_DIR.glob("*.md")) + list(REPORTS_DIR.glob("*.csv")) + list((REPORTS_DIR / "figures").glob("*.png")):
        dst = OUT / "files" / "reports" / p.relative_to(REPORTS_DIR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    readme = (ROOT / "deploy" / "hf_space" / "README.md").read_text(encoding="utf-8").split("---", 2)[2]
    (OUT / "README.md").write_text(SPACE_CARD + readme.replace(
        "- **Pipeline:** refreshes every hour inside this Space.",
        "- **Pipeline:** runs every hour (Prefect) and republishes this page's data after each run."), encoding="utf-8")
    return OUT


def upload(repo_id: str, data_only: bool = False, message: str = "Update BijliCast dashboard") -> str:
    from huggingface_hub import HfApi
    api = HfApi()
    if not data_only:
        api.create_repo(repo_id, repo_type="space", space_sdk="static", exist_ok=True, private=False)
    api.upload_folder(folder_path=str(OUT), repo_id=repo_id, repo_type="space", commit_message=message,
                      allow_patterns=["data/**"] if data_only else None,
                      delete_patterns=["data/**"] if not data_only else None)
    return f"https://huggingface.co/spaces/{repo_id}"


def publish_hourly(run_id: str) -> str | None:
    """Called by the Supervisor after each run when config/deploy.yaml enables it."""
    cfg = deploy_config()
    if not (cfg.get("hf_space") and cfg.get("hourly_push")):
        return None
    export_data(with_answers=True)
    return upload(cfg["hf_space"], data_only=True, message=f"Hourly data refresh {run_id}")


if __name__ == "__main__":
    info = export_data()
    export_site()
    print(f"exported {info['files']} JSON files (snapshot {info['snapshot_utc']}) -> {OUT}")
    if "--push" in sys.argv:
        cfg = deploy_config()
        print(upload(cfg["hf_space"], data_only="--data-only" in sys.argv))
