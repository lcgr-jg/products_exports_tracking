"""Trade-status breakdown for counterparty-Unknown flows (Kpler Trades API)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from export_pace.config import Settings, load_settings
from export_pace.flow_direction import FlowDirectionId
from export_pace.locations import LocationSelection

UNKNOWN_LABEL = "Unknown"
MIN_UNKNOWN_KB = 50.0
MIN_UNKNOWN_SHARE = 0.15

STATUS_ORDER = ["Loading", "In Transit", "Scheduled", "Delivered"]

TRADES_COLUMNS = [
    "status",
    "destination_country_name",
    "origin_country_name",
    "cargo_origin_barrels_split_by_product",
]


@dataclass(frozen=True)
class UnknownTradeStatusBreakdown:
    """Volume in country-Unknown counterparty trades, split by Kpler trade status."""

    unknown_country_kb: float
    by_status: pd.Series
    n_cargos: int

    @property
    def has_panel(self) -> bool:
        return (
            not self.by_status.empty
            and self.unknown_country_kb >= MIN_UNKNOWN_KB
            and float(self.by_status.sum()) > 0
        )


def _counterparty_country_column(flow_direction: FlowDirectionId) -> str:
    return "destination_country_name" if flow_direction == "export" else "origin_country_name"


def _trades_location_kwargs(
    flow_direction: FlowDirectionId, locations: LocationSelection
) -> list[dict]:
    """Mirror Flows location filters on the Trades API (from_* for export, to_* for import)."""
    if flow_direction == "import":
        calls: list[dict] = []
        if locations.zones:
            calls.append({"to_zones": list(locations.zones)})
        if locations.installations:
            calls.append({"to_installations": list(locations.installations)})
        return calls

    calls = []
    if locations.zones:
        calls.append({"from_zones": list(locations.zones)})
    if locations.installations:
        calls.append({"from_installations": list(locations.installations)})
    return calls


def _normalize_status(raw: object) -> str:
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return "Unknown status"
    lower = text.lower()
    for canonical in STATUS_ORDER:
        if lower == canonical.lower():
            return canonical
    return text.title()


def _status_sort_key(label: str) -> tuple[int, str]:
    try:
        return (STATUS_ORDER.index(label), label)
    except ValueError:
        return (len(STATUS_ORDER), label)


def _volume_kb(frame: pd.DataFrame) -> pd.Series:
    vol = pd.to_numeric(frame["cargo_origin_barrels_split_by_product"], errors="coerce").fillna(0)
    return vol / 1000.0


def _mock_breakdown(unknown_country_kb: float) -> UnknownTradeStatusBreakdown:
    shares = {"In Transit": 0.58, "Loading": 0.32, "Scheduled": 0.10}
    by_status = pd.Series(
        {status: unknown_country_kb * share for status, share in shares.items()}
    ).sort_values(ascending=False)
    return UnknownTradeStatusBreakdown(
        unknown_country_kb=unknown_country_kb,
        by_status=by_status,
        n_cargos=8,
    )


def should_show_unknown_detail(
    country_totals: pd.Series,
    breakdown: UnknownTradeStatusBreakdown | None,
) -> bool:
    if breakdown is None or not breakdown.has_panel:
        return False
    if UNKNOWN_LABEL not in country_totals.index:
        return False
    unknown_kb = float(country_totals[UNKNOWN_LABEL])
    total_kb = float(country_totals.sum())
    if unknown_kb < MIN_UNKNOWN_KB:
        return False
    return unknown_kb / total_kb >= MIN_UNKNOWN_SHARE if total_kb > 0 else False


def fetch_unknown_trade_status_breakdown(
    *,
    locations: LocationSelection,
    products: tuple[str, ...],
    year: int,
    month: int,
    as_of: date | None,
    flow_direction: FlowDirectionId = "export",
    with_forecast_live: bool | None = None,
    with_intra_country: bool | None = None,
    with_intra_region: bool | None = None,
    country_totals: pd.Series | None = None,
    settings: Settings | None = None,
    trades_cache: dict | None = None,
) -> UnknownTradeStatusBreakdown | None:
    """Cargo-level status split for trades whose counterparty country is Unknown."""
    if flow_direction == "net_export":
        return None

    settings = settings or load_settings()
    if country_totals is None or country_totals.empty:
        return None
    if UNKNOWN_LABEL not in country_totals.index:
        return None

    unknown_country_kb = float(country_totals[UNKNOWN_LABEL])
    if unknown_country_kb < MIN_UNKNOWN_KB:
        return None

    if settings.use_mock:
        return _mock_breakdown(unknown_country_kb)

    forecast = (
        settings.with_forecast_live if with_forecast_live is None else with_forecast_live
    )
    intra_country = (
        settings.with_intra_country if with_intra_country is None else with_intra_country
    )
    intra_region = (
        settings.with_intra_region if with_intra_region is None else with_intra_region
    )

    start = date(year, month, 1)
    end = as_of or date(year, month, calendar.monthrange(year, month)[1])
    cache_key = (
        flow_direction,
        locations.cache_key,
        products,
        start,
        end,
        forecast,
        intra_country,
        intra_region,
    )
    if trades_cache is not None and cache_key in trades_cache:
        trades = trades_cache[cache_key]
    else:
        trades = _fetch_trades(
            locations=locations,
            products=products,
            start_date=start,
            end_date=end,
            flow_direction=flow_direction,
            with_forecast=forecast,
            with_intra_country=intra_country,
            with_intra_region=intra_region,
            settings=settings,
        )
        if trades_cache is not None:
            trades_cache[cache_key] = trades

    if trades is None or trades.empty:
        return None

    country_col = _counterparty_country_column(flow_direction)
    if country_col not in trades.columns:
        return None

    is_unknown = trades[country_col].astype(str).str.strip().str.lower().eq("unknown") | trades[
        country_col
    ].isna()
    unknown_trades = trades.loc[is_unknown].copy()
    if unknown_trades.empty:
        return None

    unknown_trades["kb"] = _volume_kb(unknown_trades)
    unknown_trades["status_label"] = unknown_trades["status"].map(_normalize_status)
    grouped = unknown_trades.groupby("status_label", as_index=True)["kb"].sum()
    grouped = grouped[grouped > 0].sort_values(ascending=False)
    grouped = grouped.reindex(
        sorted(grouped.index, key=_status_sort_key)
    ).dropna()
    grouped = grouped.sort_values(ascending=False)

    return UnknownTradeStatusBreakdown(
        unknown_country_kb=unknown_country_kb,
        by_status=grouped,
        n_cargos=int(len(unknown_trades)),
    )


def _fetch_trades(
    *,
    locations: LocationSelection,
    products: tuple[str, ...],
    start_date: date,
    end_date: date,
    flow_direction: FlowDirectionId,
    with_forecast: bool,
    with_intra_country: bool,
    with_intra_region: bool,
    settings: Settings,
) -> pd.DataFrame | None:
    loc_calls = _trades_location_kwargs(flow_direction, locations)
    if not loc_calls:
        return None

    try:
        from kpler.sdk import Platform
        from kpler.sdk.configuration import Configuration
        from kpler.sdk.resources.trades import Trades
    except ImportError:
        return None

    if not settings.kpler_email or not settings.kpler_password:
        return None

    client = Trades(
        Configuration(Platform.Liquids, settings.kpler_email, settings.kpler_password)
    )
    common = dict(
        products=list(products),
        start_date=start_date,
        end_date=end_date,
        with_forecast=with_forecast,
        with_intra_country=with_intra_country,
        with_intra_region=with_intra_region,
        columns=TRADES_COLUMNS,
    )

    frames: list[pd.DataFrame] = []
    for loc_kw in loc_calls:
        try:
            frames.append(client.get(**common, **loc_kw))
        except Exception:
            continue

    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)
