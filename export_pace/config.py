from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# override=True so values in .env win over stale shell exports (e.g. USE_MOCK=true).
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)


@dataclass(frozen=True)
class Settings:
    use_mock: bool
    kpler_email: str | None
    kpler_password: str | None
    unit: str = "kb"
    with_forecast_live: bool = False
    with_forecast_hist: bool = False
    only_realized_hist: bool = True
    with_intra_country: bool = False
    with_intra_region: bool = True
    n_history: int = 5
    use_disk_cache: bool = True


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def kpler_sdk_available() -> bool:
    try:
        import kpler.sdk  # noqa: F401
        return True
    except ImportError:
        return False


def load_settings() -> Settings:
    return Settings(
        use_mock=_env_bool("USE_MOCK", default=False),
        kpler_email=os.getenv("KPLER_EMAIL"),
        kpler_password=os.getenv("KPLER_PASSWORD"),
        use_disk_cache=_env_bool("USE_DISK_CACHE", default=True),
    )
