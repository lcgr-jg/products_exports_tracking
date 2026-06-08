from __future__ import annotations

import calendar
from datetime import date

import pandas as pd


def to_dom_cumulative(daily: pd.Series, *, as_of: date | None = None) -> pd.Series:
    """Reindex to day-of-month (1..N) and cumulative-sum. as_of truncates the live month."""
    s = daily.copy()
    if as_of is not None:
        s = s[s.index.date <= as_of]
    cum = s.cumsum()
    cum.index = cum.index.day
    return cum


def prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def build_history_matrix(
    month: int,
    years: list[int],
    get_daily,
) -> pd.DataFrame:
    """day_of_month (rows) x year (cols) cumulative-export matrix."""
    return pd.DataFrame(
        {y: to_dom_cumulative(get_daily(y, month)) for y in years}
    ).sort_index()


def build_history_daily_matrix(
    month: int,
    years: list[int],
    get_daily,
) -> pd.DataFrame:
    """day_of_month (rows) x year (cols) non-cumulative daily export matrix."""
    frames: dict[int, pd.Series] = {}
    for y in years:
        daily = get_daily(y, month)
        if daily.empty:
            continue
        s = daily.copy()
        s.index = s.index.day
        frames[y] = s
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def build_pace_heatmap(
    hist_cumulative: pd.DataFrame,
    current: pd.Series,
    target_year: int,
    days_in_month: int,
    *,
    signed: bool = False,
) -> pd.DataFrame:
    """Years × day-of-month matrix: cumulative flows as % of that year's month total."""
    combined = hist_cumulative.copy()
    combined[target_year] = current
    rows: dict[int, pd.Series] = {}
    dom_index = list(range(1, days_in_month + 1))
    for year in sorted(combined.columns):
        series = combined[year].reindex(dom_index).ffill().fillna(0)
        if signed:
            nonzero = series[series != 0]
            last_dom = int(nonzero.index.max()) if not nonzero.empty else days_in_month
        else:
            last_dom = int(series[series > 0].index.max()) if (series > 0).any() else days_in_month
        eom = float(series.loc[last_dom]) if last_dom in series.index else float(series.max())
        denom = abs(eom) if signed else (eom if eom > 0 else 1.0)
        if denom <= 0:
            denom = 1.0
        pct = series / denom * 100
        rows[year] = pct if signed else pct.clip(0, 100)
    return pd.DataFrame(rows).T


def detect_anomaly_days(
    current_daily: pd.Series,
    hist_daily: pd.DataFrame,
    *,
    sigma: float = 2.0,
    signed: bool = False,
) -> list[int]:
    """Flag unusual daily volumes vs historical same-DOM distribution."""
    flagged: list[int] = []
    for day, value in current_daily.items():
        if day not in hist_daily.index or value != value:
            continue
        ref = hist_daily.loc[day].dropna()
        if len(ref) < 2:
            continue
        med = float(ref.median())
        std = float(ref.std())
        if std <= 0:
            continue
        if signed:
            unusual = abs(value - med) > sigma * std
        else:
            unusual = value > med + sigma * std
        if unusual:
            flagged.append(int(day))
    return sorted(flagged)


def seasonal_band(hist: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=hist.index)
    out["median"] = hist.median(axis=1)
    out["p25"] = hist.quantile(0.25, axis=1)
    out["p75"] = hist.quantile(0.75, axis=1)
    out["min"] = hist.min(axis=1)
    out["max"] = hist.max(axis=1)
    return out


def percentile_rank_at_day(hist: pd.DataFrame, day: int, value: float) -> float | None:
    """Share of prior same-month cumulative totals strictly below *value* at *day* (0–100)."""
    if value != value or day not in hist.index:
        return None
    row = hist.loc[day].dropna()
    if row.empty:
        return None
    return float((row < value).mean() * 100)


def resolve_as_of(
    target_year: int,
    month: int,
    as_of_day: int | None,
    *,
    today: date | None = None,
) -> tuple[date | None, bool, int]:
    """Return (as_of date, is_live_month, days_in_month)."""
    today = today or date.today()
    days_in_month = calendar.monthrange(target_year, month)[1]
    is_live_month = target_year == today.year and month == today.month

    if as_of_day is not None:
        day = min(max(1, as_of_day), days_in_month)
        return date(target_year, month, day), is_live_month, days_in_month
    if is_live_month:
        return today, True, days_in_month
    return None, False, days_in_month
