"""Fetch raw files from ISMO and Open-Meteo into data/raw and record them in manifest.csv.

Raw files are saved exactly as received and never edited afterwards.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import manifest as mf
from .config import RAW_DIR, sources

USER_AGENT = "BijliCast/0.1 (HackInsight 2026 student project; github.com/nabeelali0707/hack-insight-hacakthon)"


@dataclass
class FetchResult:
    file_id: str
    status: str   # new | verified | reloaded | changed | failed
    detail: str = ""


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = USER_AGENT
    return s


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ismo_url(url: str) -> str:
    """Rewrite moved ISMO links to the current storage host and percent-encode the path."""
    rw = sources()["ismo"]["url_rewrite"]
    if url.startswith(rw["from"]):
        url = rw["to"] + url[len(rw["from"]):]
    scheme, rest = url.split("://", 1)
    host, path = rest.split("/", 1)
    return f"{scheme}://{host}/" + quote(path, safe="/()")


def _ismo_token(url: str) -> str:
    """ISMO appends `_ismo_<random>` to every upload; its first 10 chars identify the file."""
    m = re.search(r"_ismo_([A-Za-z0-9]+)\.xlsx$", url)
    return m.group(1)[:10] if m else re.sub(r"\W", "", url)[-10:]


def _store(entries: dict, *, file_id: str, source: str, title: str, period: str, url: str,
           dest: Path, licence: str, immutable: bool, session: requests.Session,
           timeout: int = 120) -> FetchResult:
    """Download `url` to `dest` (or reload it if present) and reconcile with the manifest."""
    known = entries.get(file_id)
    if dest.exists() and known and mf.sha256_file(dest) == known.sha256:
        return FetchResult(file_id, "reloaded")

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return FetchResult(file_id, "failed", str(exc)[:200])
    dest.write_bytes(resp.content)
    sha = mf.sha256_file(dest)

    status, detail = "new", ""
    if known:
        if known.sha256 == sha:
            status = "verified"
        else:
            status = "changed"
            detail = f"sha256 {known.sha256[:12]}… -> {sha[:12]}… ({'publisher changed an immutable file' if immutable else 'revisable source updated'})"
    entries[file_id] = mf.ManifestEntry(
        file_id=file_id, source=source, title=title, period=period, query=url,
        local_path=mf.relpath(dest), fetched_at_utc=_now_utc(), sha256=sha,
        bytes=dest.stat().st_size, licence=licence, immutable=immutable,
    )
    return FetchResult(file_id, status, detail)


# ---------------------------------------------------------------- ISMO

def ismo_registry() -> list[dict]:
    """Every registered ISMO file with its stable file_id (shared by fetch and warehouse)."""
    cfg = sources()["ismo"]
    out = []
    for kind, source, prefix in (("disco_monthly", "ismo_disco_monthly", "ismo_disco"),
                                 ("hourly_marginal_price", "ismo_hourly_price", "ismo_price")):
        for item in cfg[kind]:
            file_id = f"{prefix}_{item['period'].replace('..', '_')}_{_ismo_token(item['url'])}"
            out.append({**item, "file_id": file_id, "source": source, "fetch_url": _ismo_url(item["url"]),
                        "dest": RAW_DIR / "ismo" / f"{file_id}.xlsx"})
    return out


def fetch_ismo(entries: dict, session: requests.Session | None = None) -> list[FetchResult]:
    session = session or _session()
    licence = sources()["ismo"]["licence"].strip()
    results = []
    for item in ismo_registry():
        results.append(_store(
            entries, file_id=item["file_id"], source=item["source"], title=item["title"], period=item["period"],
            url=item["fetch_url"], dest=item["dest"], licence=licence, immutable=True, session=session,
        ))
        time.sleep(0.3)  # be gentle with a government server
    return results


# ---------------------------------------------------------------- Open-Meteo

def _om_params(ent: dict, hourly: list[str], **extra) -> str:
    params = {"latitude": ent["lat"], "longitude": ent["lon"], "hourly": ",".join(hourly),
              "timezone": "GMT", "format": "csv", **extra}
    return urlencode(params)


def fetch_weather_archive(entries: dict, session: requests.Session | None = None) -> list[FetchResult]:
    """Hourly ERA5 reanalysis per entity city, UTC, pinned date range (reproducible)."""
    session = session or _session()
    om = sources()["open_meteo"]
    results = []
    for code, ent in om["entities"].items():
        url = om["archive_endpoint"] + "?" + _om_params(
            ent, om["hourly_vars"], start_date=om["archive_start"], end_date=om["archive_end"])
        file_id = f"weather_archive_{code}"
        dest = RAW_DIR / "open_meteo" / "archive" / f"{code}_{om['archive_start']}_{om['archive_end']}.csv"
        results.append(_store(
            entries, file_id=file_id, source="open_meteo_archive", title=f"ERA5 hourly weather, {ent['city']}",
            period=f"{om['archive_start']}..{om['archive_end']}", url=url, dest=dest,
            licence=om["licence"], immutable=False, session=session, timeout=300,
        ))
        time.sleep(1.0)
    return results


def fetch_weather_forecast(entries: dict, session: requests.Session | None = None) -> list[FetchResult]:
    """Live hourly snapshot per entity: last 14 days observed/analysed + 16-day forecast."""
    session = session or _session()
    om = sources()["open_meteo"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H00Z")
    results = []
    for code, ent in om["entities"].items():
        url = om["forecast_endpoint"] + "?" + _om_params(ent, om["hourly_vars"], past_days=14, forecast_days=16)
        file_id = f"weather_forecast_{code}_{stamp}"
        dest = RAW_DIR / "open_meteo" / "forecast" / code / f"{stamp}.csv"
        results.append(_store(
            entries, file_id=file_id, source="open_meteo_forecast", title=f"Open-Meteo forecast snapshot, {ent['city']}",
            period=stamp, url=url, dest=dest, licence=om["licence"], immutable=False, session=session,
        ))
        time.sleep(0.3)
    return results


def fetch_all(include_forecast: bool = True) -> list[FetchResult]:
    entries = mf.load()
    session = _session()
    results = fetch_ismo(entries, session) + fetch_weather_archive(entries, session)
    if include_forecast:
        results += fetch_weather_forecast(entries, session)
    mf.save(entries)
    return results
