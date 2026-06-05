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
