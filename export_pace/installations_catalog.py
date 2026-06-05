from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from export_pace.config import load_settings

INSTALLATIONS_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "installations"
CACHE_TTL_SEC = 7 * 24 * 3600
LOOKBACK_DAYS = 365
MIN_FLOW_KB = 1.0

SKIP_COLUMNS = frozenset({"Date", "Period End Date", "Total"})

_MEMORY_CACHE: dict[str, tuple[float, list[str]]] = {}


def zone_names_from_values(zone_values: list[str] | None) -> list[str]:
    names: list[str] = []
    for raw in zone_values or []:
        if not isinstance(raw, str):
            continue
        if raw.startswith("zone:"):
            names.append(raw.removeprefix("zone:"))
        elif raw.strip():
            names.append(raw.strip())
    return sorted(set(names))


def _cache_key(zones: list[str], products: list[str]) -> str:
    payload = json.dumps({"zones": zones, "products": sorted(products)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return INSTALLATIONS_CACHE_DIR / f"{key}.json"


def clear_installation_catalog_cache() -> None:
    _MEMORY_CACHE.clear()
    if INSTALLATIONS_CACHE_DIR.exists():
        for path in INSTALLATIONS_CACHE_DIR.glob("*.json"):
            path.unlink(missing_ok=True)


def _read_disk_cache(key: str) -> list[str] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - payload.get("fetched_at", 0) > CACHE_TTL_SEC:
            return None
        return list(payload.get("installations", []))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _write_disk_cache(key: str, installations: list[str]) -> None:
    INSTALLATIONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "installations": installations}
    _cache_path(key).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _flows_client():
    from kpler.sdk import Platform
    from kpler.sdk.configuration import Configuration
    from kpler.sdk.resources.flows import Flows

    settings = load_settings()
    if settings.use_mock or not settings.kpler_email or not settings.kpler_password:
        return None
    return Flows(Configuration(Platform.Liquids, settings.kpler_email, settings.kpler_password))


def _installations_from_flows_df(df: pd.DataFrame) -> list[str]:
    numeric = df.select_dtypes("number")
    cols = [c for c in numeric.columns if c not in SKIP_COLUMNS]
    if not cols:
        return []
    totals = numeric[cols].sum().sort_values(ascending=False)
    return [str(name) for name, total in totals.items() if float(total) >= MIN_FLOW_KB]


def _fetch_installations_for_zone(zone: str, products: list[str]) -> list[str]:
    client = _flows_client()
    if client is None:
        return []

    from kpler.sdk import (
        FlowsDirection,
        FlowsMeasurementUnit,
        FlowsPeriod,
        FlowsSplit,
    )

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    df = client.get(
        flow_direction=[FlowsDirection.Export],
        split=[FlowsSplit.OriginInstallations],
        granularity=[FlowsPeriod.Daily],
        from_zones=[zone],
        products=products,
        unit=[FlowsMeasurementUnit.KB],
        start_date=start,
        end_date=end,
        with_forecast=False,
        only_realized=True,
    )
    return _installations_from_flows_df(df)


def fetch_installations_catalog(
    zones: list[str],
    products: list[str],
    *,
    force_refresh: bool = False,
) -> list[str]:
    """Installations with export flows in the last year for zones + products."""
    if not zones or not products:
        return []

    key = _cache_key(zones, products)
    if not force_refresh:
        if key in _MEMORY_CACHE:
            ts, names = _MEMORY_CACHE[key]
            if time.time() - ts <= CACHE_TTL_SEC:
                return names
        cached = _read_disk_cache(key)
        if cached is not None:
            _MEMORY_CACHE[key] = (time.time(), cached)
            return cached

    merged: list[str] = []
    seen: set[str] = set()
    for zone in zones:
        for name in _fetch_installations_for_zone(zone, products):
            if name not in seen:
                seen.add(name)
                merged.append(name)

    _MEMORY_CACHE[key] = (time.time(), merged)
    _write_disk_cache(key, merged)
    print(f"Cached {len(merged)} installations for zones={zones} products={products}")
    return merged


def installation_options_from_names(names: list[str]) -> list[dict]:
    return [
        {"label": f"{name} (installation)", "value": f"installation:{name}"}
        for name in names
    ]
