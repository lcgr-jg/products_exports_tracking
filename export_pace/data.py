from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from export_pace.config import Settings, load_settings
from export_pace.locations import LocationSelection, location_label, overlap_warning
from export_pace.flows_disk_cache import clear_flows_disk_cache, load_flows, save_flows
from export_pace.transform import (
    build_history_daily_matrix,
    build_history_matrix,
    build_pace_heatmap,
    detect_anomaly_days,
    percentile_rank_at_day,
    prev_month,
    resolve_as_of,
    seasonal_band,
    to_dom_cumulative,
)


@dataclass(frozen=True)
class ViewResult:
    current: pd.Series
    current_daily: pd.Series
    last_mo: pd.Series
    last_yr: pd.Series
    band: pd.DataFrame
    month: int
    target_year: int
    n_history: int
    unit: str
    product_label: str
    location_label: str
    as_of: date | None
    latest_data_day: date | None
    is_live_month: bool
    days_in_month: int
    use_mock: bool
    warning: str | None
    hist_by_year: pd.DataFrame
    percentile_rank: float | None
    destinations_mtd: pd.Series
    origin_daily: pd.DataFrame | None
    origin_cumulative: pd.DataFrame | None
    location_series: dict[str, pd.Series]
    product_series: dict[str, pd.Series]
    heatmap_pct: pd.DataFrame
    anomaly_days: list[int]


def filter_label(values: list[str], *, sep: str = ", ") -> str:
    if not values:
        return "—"
    return values[0] if len(values) == 1 else sep.join(values)


class ExportDataService:
    """Parameterized Kpler Flows fetcher with zone / installation split."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self._flows_client = None
        self._bulk_cache: dict[tuple, pd.DataFrame] = {}
        self._daily_cache: dict[tuple, pd.Series] = {}
        self._split_cache: dict[tuple, pd.DataFrame] = {}

    def _get_flows_client(self):
        if self._flows_client is None:
            try:
                from kpler.sdk import Platform
                from kpler.sdk.configuration import Configuration
                from kpler.sdk.resources.flows import Flows
            except ImportError as exc:
                raise RuntimeError(
                    "kpler-sdk is not installed in this Python environment. "
                    "Run: pip install kpler-sdk"
                ) from exc

            if not self.settings.kpler_email or not self.settings.kpler_password:
                raise RuntimeError(
                    "KPLER_EMAIL and KPLER_PASSWORD are required when USE_MOCK=false"
                )
            config = Configuration(
                Platform.Liquids,
                self.settings.kpler_email,
                self.settings.kpler_password,
            )
            self._flows_client = Flows(config)
        return self._flows_client

    @staticmethod
    def _bulk_start_date(target_year: int, n_history: int) -> date:
        return date(target_year - n_history - 1, 1, 1)

    @staticmethod
    def _merge_flow_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame(columns=["Date", "Total"])
        if len(frames) == 1:
            return frames[0]
        merged = frames[0][["Date", "Total"]].copy()
        for frame in frames[1:]:
            other = frame[["Date", "Total"]].rename(columns={"Total": "_other"})
            merged = merged.merge(other, on="Date", how="outer")
            merged["Total"] = merged["Total"].fillna(0) + merged["_other"].fillna(0)
            merged = merged.drop(columns=["_other"])
        return merged.sort_values("Date").reset_index(drop=True)

    def _fetch_flows_bulk(
        self,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        target_year: int,
        n_history: int,
        live: bool,
        with_forecast_live: bool | None = None,
    ) -> pd.DataFrame:
        forecast_live = (
            self.settings.with_forecast_live
            if with_forecast_live is None
            else with_forecast_live
        )
        key = (
            live,
            locations.cache_key,
            products,
            self.settings.unit,
            forecast_live if live else self.settings.with_forecast_hist,
            False if live else self.settings.only_realized_hist,
            self.settings.with_intra_country,
        )
        if key in self._bulk_cache:
            return self._bulk_cache[key]

        from kpler.sdk import (
            FlowsDirection,
            FlowsMeasurementUnit,
            FlowsPeriod,
            FlowsSplit,
        )

        unit_enum = {
            "kb": FlowsMeasurementUnit.KB,
            "kbd": FlowsMeasurementUnit.KBD,
        }[self.settings.unit]
        common = dict(
            flow_direction=[FlowsDirection.Export],
            split=[FlowsSplit.Total],
            granularity=[FlowsPeriod.Daily],
            products=list(products),
            unit=[unit_enum],
            start_date=self._bulk_start_date(target_year, n_history),
            end_date=date.today(),
            with_forecast=forecast_live if live else self.settings.with_forecast_hist,
            only_realized=False if live else self.settings.only_realized_hist,
            with_intra_country=self.settings.with_intra_country,
        )

        # Kpler rejects from_zones and from_installations in the same request.
        frames: list[pd.DataFrame] = []
        client = self._get_flows_client()
        if locations.zones:
            frames.append(client.get(from_zones=list(locations.zones), **common))
        if locations.installations:
            frames.append(
                client.get(from_installations=list(locations.installations), **common)
            )

        disk_key = ("total", *key)
        if not live and self.settings.use_disk_cache:
            cached = load_flows(disk_key)
            if cached is not None:
                self._bulk_cache[key] = cached
                return cached

        df = self._merge_flow_frames(frames)
        self._bulk_cache[key] = df
        if not live and self.settings.use_disk_cache:
            save_flows(disk_key, df)
        return df

    @staticmethod
    def _merge_wide_flow_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame(columns=["Date"])
        if len(frames) == 1:
            return frames[0]
        parts: list[pd.DataFrame] = []
        for frame in frames:
            part = frame.copy()
            part["Date"] = pd.to_datetime(part["Date"])
            for col in part.columns:
                if col in ("Date", "Period End Date"):
                    continue
                part[col] = pd.to_numeric(part[col], errors="coerce")
            parts.append(part)
        full = pd.concat(parts, ignore_index=True)
        num_cols = [
            c
            for c in full.columns
            if c not in ("Date", "Period End Date")
            and pd.to_numeric(full[c], errors="coerce").notna().any()
        ]
        for col in num_cols:
            full[col] = pd.to_numeric(full[col], errors="coerce")
        merged = full.groupby("Date", as_index=False)[num_cols].sum(min_count=1)
        return merged.sort_values("Date").reset_index(drop=True)

    def _fetch_flows_split(
        self,
        *,
        split,
        locations: LocationSelection,
        products: tuple[str, ...],
        start_date: date,
        end_date: date,
        live: bool,
        with_forecast_live: bool | None = None,
    ) -> pd.DataFrame:
        forecast_live = (
            self.settings.with_forecast_live
            if with_forecast_live is None
            else with_forecast_live
        )
        key = (
            split.name if hasattr(split, "name") else str(split),
            live,
            locations.cache_key,
            products,
            start_date,
            end_date,
            self.settings.unit,
            forecast_live if live else self.settings.with_forecast_hist,
            False if live else self.settings.only_realized_hist,
            self.settings.with_intra_country,
        )
        if key in self._split_cache:
            return self._split_cache[key]

        if self.settings.use_mock:
            df = self._mock_split_flows(
                split=split,
                locations=locations,
                products=products,
                start_date=start_date,
                end_date=end_date,
            )
            self._split_cache[key] = df
            return df

        from kpler.sdk import (
            FlowsDirection,
            FlowsMeasurementUnit,
            FlowsPeriod,
        )

        unit_enum = {
            "kb": FlowsMeasurementUnit.KB,
            "kbd": FlowsMeasurementUnit.KBD,
        }[self.settings.unit]
        common = dict(
            flow_direction=[FlowsDirection.Export],
            split=[split],
            granularity=[FlowsPeriod.Daily],
            products=list(products),
            unit=[unit_enum],
            start_date=start_date,
            end_date=end_date,
            with_forecast=forecast_live if live else self.settings.with_forecast_hist,
            only_realized=False if live else self.settings.only_realized_hist,
            with_intra_country=self.settings.with_intra_country,
        )

        frames: list[pd.DataFrame] = []
        client = self._get_flows_client()
        if locations.zones:
            frames.append(client.get(from_zones=list(locations.zones), **common))
        if locations.installations:
            frames.append(
                client.get(from_installations=list(locations.installations), **common)
            )

        df = self._merge_wide_flow_frames(frames)
        self._split_cache[key] = df
        return df

    def _mock_split_flows(
        self,
        *,
        split,
        locations: LocationSelection,
        products: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        from kpler.sdk import FlowsSplit

        idx = pd.date_range(start_date, end_date, freq="D")
        seed = hash((locations.cache_key, products, split)) % (2**31)
        rng = np.random.default_rng(seed)
        n = len(idx)

        if split == FlowsSplit.DestinationCountries:
            labels = ["Singapore Republic", "South Africa", "India", "United Arab Emirates", "Unknown"]
        else:
            labels = list(locations.installations) or [
                "Jamnagar Refinery",
                "Vadinar Refinery",
                "New Mangalore Refinery",
            ]

        data = {"Date": idx}
        for label in labels:
            data[label] = rng.uniform(50, 250, n) * (1 + 0.1 * rng.random(n))
        return pd.DataFrame(data)

    @staticmethod
    def _split_df_to_month_matrix(
        df: pd.DataFrame, year: int, month: int, *, as_of: date | None = None
    ) -> pd.DataFrame:
        if df.empty or "Date" not in df.columns:
            return pd.DataFrame()
        dt = pd.to_datetime(df["Date"])
        mask = (dt.dt.year == year) & (dt.dt.month == month)
        if as_of is not None:
            mask &= dt.dt.date <= as_of
        sliced = df.loc[mask].copy()
        if sliced.empty:
            return pd.DataFrame()
        sliced["Date"] = pd.to_datetime(sliced["Date"])
        meta = {"Date", "Period End Date", "Total"}
        value_cols = [c for c in sliced.columns if c not in meta]
        for col in value_cols:
            sliced[col] = pd.to_numeric(sliced[col], errors="coerce").fillna(0)
        daily = sliced.set_index("Date")[value_cols]
        daily.index = daily.index.day
        return daily.sort_index()

    def get_destinations_mtd(
        self,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        year: int,
        month: int,
        as_of: date | None,
        with_forecast_live: bool | None = None,
    ) -> pd.Series:
        from kpler.sdk import FlowsSplit

        start = date(year, month, 1)
        end = as_of or date(year, month, calendar.monthrange(year, month)[1])
        df = self._fetch_flows_split(
            split=FlowsSplit.DestinationCountries,
            locations=locations,
            products=products,
            start_date=start,
            end_date=end,
            live=True,
            with_forecast_live=with_forecast_live,
        )
        daily = self._split_df_to_month_matrix(df, year, month, as_of=as_of)
        if daily.empty:
            return pd.Series(dtype=float)
        totals = daily.sum(axis=0).sort_values(ascending=False)
        totals = totals[totals > 0]
        return totals

    def get_origin_daily_breakdown(
        self,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        year: int,
        month: int,
        as_of: date | None,
        with_forecast_live: bool | None = None,
    ) -> pd.DataFrame | None:
        """Daily exports by origin installation — only when a single zone is selected."""
        if len(locations.zones) != 1 or locations.installations:
            return None
        from kpler.sdk import FlowsSplit

        start = date(year, month, 1)
        end = as_of or date(year, month, calendar.monthrange(year, month)[1])
        df = self._fetch_flows_split(
            split=FlowsSplit.OriginInstallations,
            locations=locations,
            products=products,
            start_date=start,
            end_date=end,
            live=True,
            with_forecast_live=with_forecast_live,
        )
        daily = self._split_df_to_month_matrix(df, year, month, as_of=as_of)
        if daily.empty:
            return None
        return daily

    def get_location_series(
        self,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        year: int,
        month: int,
        target_year: int,
        n_history: int,
        as_of: date | None,
        with_forecast_live: bool | None = None,
    ) -> dict[str, pd.Series]:
        """Per-zone / per-installation cumulative MTD curves for the selected month."""
        labels: list[tuple[str, LocationSelection]] = []
        for zone in locations.zones:
            labels.append((zone, LocationSelection((zone,), ())))
        for inst in locations.installations:
            labels.append((inst, LocationSelection((), (inst,))))
        if len(labels) < 2:
            return {}

        out: dict[str, pd.Series] = {}
        for label, loc in labels:
            live_daily = self.get_export_daily(
                year,
                month,
                locations=loc,
                products=products,
                target_year=target_year,
                n_history=n_history,
                live=True,
                with_forecast_live=with_forecast_live,
            )
            if as_of is not None:
                live_daily = live_daily[live_daily.index.date <= as_of]
            if not live_daily.empty:
                out[label] = to_dom_cumulative(live_daily)
        return out

    def get_product_series(
        self,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        year: int,
        month: int,
        target_year: int,
        n_history: int,
        as_of: date | None,
        with_forecast_live: bool | None = None,
    ) -> dict[str, pd.Series]:
        """Per-product cumulative MTD curves when multiple products are selected."""
        if len(products) < 2:
            return {}
        out: dict[str, pd.Series] = {}
        for product in products:
            live_daily = self.get_export_daily(
                year,
                month,
                locations=locations,
                products=(product,),
                target_year=target_year,
                n_history=n_history,
                live=True,
                with_forecast_live=with_forecast_live,
            )
            if as_of is not None:
                live_daily = live_daily[live_daily.index.date <= as_of]
            if not live_daily.empty:
                out[product] = to_dom_cumulative(live_daily)
        return out

    @staticmethod
    def _flows_df_to_daily(df: pd.DataFrame, year: int, month: int) -> pd.Series:
        dt = pd.to_datetime(df["Date"])
        if "Total" in df.columns:
            values = pd.to_numeric(df["Total"], errors="coerce")
        else:
            values = df.select_dtypes("number").sum(axis=1)
        s = pd.Series(values.to_numpy(), index=dt, name="export")
        return s[(s.index.month == month) & (s.index.year == year)].sort_index()

    def _mock_export_daily(
        self,
        year: int,
        month: int,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        base: float = 600.0,
        seed: int = 0,
    ) -> pd.Series:
        filter_seed = hash((locations.cache_key, products)) % (2**31)
        rng = np.random.default_rng(seed + filter_seed + year * 100 + month)
        n = calendar.monthrange(year, month)[1]
        trend = 1.0 + 0.03 * (year - 2020)
        seasonal = 1.0 + 0.12 * np.sin((month - 1) / 12 * 2 * np.pi)
        mean_daily = base * trend * seasonal
        cargo = 380.0
        daily = rng.poisson(1.6, n) * cargo * rng.uniform(0.6, 1.4, n)
        daily = daily * (mean_daily / max(daily.mean(), 1e-9))
        idx = pd.date_range(date(year, month, 1), periods=n, freq="D")
        return pd.Series(daily, index=idx, name="export")

    def get_export_daily(
        self,
        year: int,
        month: int,
        *,
        locations: LocationSelection,
        products: tuple[str, ...],
        target_year: int,
        n_history: int,
        live: bool = False,
        with_forecast_live: bool | None = None,
    ) -> pd.Series:
        forecast_live = (
            self.settings.with_forecast_live
            if with_forecast_live is None
            else with_forecast_live
        )
        key = (
            year,
            month,
            live,
            locations.cache_key,
            products,
            target_year,
            n_history,
            forecast_live if live else self.settings.with_forecast_hist,
        )
        if key in self._daily_cache:
            return self._daily_cache[key]

        if self.settings.use_mock:
            series = self._mock_export_daily(year, month, locations=locations, products=products)
        else:
            df = self._fetch_flows_bulk(
                locations=locations,
                products=products,
                target_year=target_year,
                n_history=n_history,
                live=live,
                with_forecast_live=with_forecast_live,
            )
            series = self._flows_df_to_daily(df, year, month)

        self._daily_cache[key] = series
        return series

    def refresh_live_cache(self) -> None:
        """Clear cached live-month API pulls so the next view re-fetches from Kpler."""
        self._bulk_cache = {k: v for k, v in self._bulk_cache.items() if not k[0]}
        self._daily_cache = {k: v for k, v in self._daily_cache.items() if not k[2]}
        self._split_cache = {k: v for k, v in self._split_cache.items() if not k[1]}
        clear_flows_disk_cache()

    def build_view(
        self,
        *,
        locations: LocationSelection,
        products: list[str],
        month: int,
        target_year: int,
        n_history: int | None = None,
        as_of_day: int | None = None,
        with_forecast_live: bool | None = None,
        compare_locations: bool = False,
        compare_products: bool = False,
    ) -> ViewResult:
        if locations.is_empty:
            raise ValueError("Select at least one zone or installation")
        if not products:
            raise ValueError("Select at least one product")

        n_history = n_history if n_history is not None else self.settings.n_history
        product_tuple = tuple(products)
        as_of, is_live_month, days_in_month = resolve_as_of(target_year, month, as_of_day)

        get_daily: Callable[[int, int], pd.Series] = lambda y, m: self.get_export_daily(
            y,
            m,
            locations=locations,
            products=product_tuple,
            target_year=target_year,
            n_history=n_history,
            live=False,
            with_forecast_live=with_forecast_live,
        )

        hist_years = list(range(target_year - n_history, target_year))
        hist = build_history_matrix(month, hist_years, get_daily)
        hist_daily = build_history_daily_matrix(month, hist_years, get_daily)
        band = seasonal_band(hist)

        live_daily = self.get_export_daily(
            target_year,
            month,
            locations=locations,
            products=product_tuple,
            target_year=target_year,
            n_history=n_history,
            live=True,
            with_forecast_live=with_forecast_live,
        )
        if as_of is not None:
            live_daily = live_daily[live_daily.index.date <= as_of]

        current = to_dom_cumulative(live_daily)
        current_daily = live_daily.copy()
        current_daily.index = current_daily.index.day
        latest_data_day = (
            live_daily.index[-1].date() if not live_daily.empty else None
        )

        last_yr = to_dom_cumulative(get_daily(target_year - 1, month))
        py, pm = prev_month(target_year, month)
        last_mo = to_dom_cumulative(get_daily(py, pm))

        dom = as_of.day if as_of is not None else (int(current.index[-1]) if len(current.index) else 1)
        if dom in current.index:
            mtd_value = float(current.loc[dom])
        else:
            prior = current[current.index <= dom]
            mtd_value = float(prior.iloc[-1]) if len(prior) else float("nan")
        pct_rank = percentile_rank_at_day(hist, dom, mtd_value)

        destinations_mtd = self.get_destinations_mtd(
            locations=locations,
            products=product_tuple,
            year=target_year,
            month=month,
            as_of=as_of,
            with_forecast_live=with_forecast_live,
        )
        origin_daily = self.get_origin_daily_breakdown(
            locations=locations,
            products=product_tuple,
            year=target_year,
            month=month,
            as_of=as_of,
            with_forecast_live=with_forecast_live,
        )
        origin_cumulative = origin_daily.cumsum() if origin_daily is not None else None

        location_series: dict[str, pd.Series] = {}
        if compare_locations:
            location_series = self.get_location_series(
                locations=locations,
                products=product_tuple,
                year=target_year,
                month=month,
                target_year=target_year,
                n_history=n_history,
                as_of=as_of,
                with_forecast_live=with_forecast_live,
            )

        product_series: dict[str, pd.Series] = {}
        if compare_products:
            product_series = self.get_product_series(
                locations=locations,
                products=product_tuple,
                year=target_year,
                month=month,
                target_year=target_year,
                n_history=n_history,
                as_of=as_of,
                with_forecast_live=with_forecast_live,
            )

        heatmap_pct = build_pace_heatmap(hist, current, target_year, days_in_month)
        anomaly_days = detect_anomaly_days(current_daily, hist_daily)

        return ViewResult(
            current=current,
            current_daily=current_daily,
            last_mo=last_mo,
            last_yr=last_yr,
            band=band,
            month=month,
            target_year=target_year,
            n_history=n_history,
            unit=self.settings.unit,
            product_label=filter_label(products),
            location_label=location_label(locations),
            as_of=as_of,
            latest_data_day=latest_data_day,
            is_live_month=is_live_month,
            days_in_month=days_in_month,
            use_mock=self.settings.use_mock,
            warning=overlap_warning(locations),
            hist_by_year=hist,
            percentile_rank=pct_rank,
            destinations_mtd=destinations_mtd,
            origin_daily=origin_daily,
            origin_cumulative=origin_cumulative,
            location_series=location_series,
            product_series=product_series,
            heatmap_pct=heatmap_pct,
            anomaly_days=anomaly_days,
        )


_DATA_SERVICE: ExportDataService | None = None


def get_data_service() -> ExportDataService:
    global _DATA_SERVICE
    if _DATA_SERVICE is None:
        _DATA_SERVICE = ExportDataService()
    return _DATA_SERVICE
