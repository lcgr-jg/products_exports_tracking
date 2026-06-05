"""Optional on-disk parquet cache for Kpler Flows bulk pulls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "flows"


def _key_path(key: tuple) -> Path:
    digest = hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()[:24]
    return _CACHE_DIR / f"{digest}.parquet"


def load_flows(key: tuple) -> pd.DataFrame | None:
    path = _key_path(key)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except OSError:
        return None


def save_flows(key: tuple, df: pd.DataFrame) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_key_path(key), index=False)


def clear_flows_disk_cache() -> None:
    if not _CACHE_DIR.exists():
        return
    for path in _CACHE_DIR.glob("*.parquet"):
        path.unlink(missing_ok=True)
