"""HTML helpers for the diesel exports email report (no Dash)."""
from __future__ import annotations

import base64
import calendar
from datetime import datetime

import plotly.graph_objects as go

from export_pace.data import ViewResult
from export_pace.figure import _pct_delta, _value_at_day


def fig_to_img_tag(fig: go.Figure, width: int = 860, height: int = 400) -> str:
    """Render a Plotly figure to a base64 PNG inline img tag."""
    img_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'width="{width}" style="max-width:100%;display:block;">'
    )


def status_line_text(view: ViewResult, *, refreshed_at: datetime | None = None) -> str:
    parts: list[str] = []
    if view.latest_data_day:
        parts.append(f"Latest Kpler flow date: {view.latest_data_day.strftime('%d %b %Y')}")
    if view.as_of:
        parts.append(f"Chart truncated at: {view.as_of.strftime('%d %b %Y')}")
    if refreshed_at:
        parts.append(f"Refreshed: {refreshed_at.strftime('%H:%M:%S')}")
    if view.use_mock:
        parts.append("MOCK data")
    if view.anomaly_days:
        parts.append(f"Anomaly days: {', '.join(str(d) for d in view.anomaly_days)}")
    parts.append(
        "Intra-country: "
        f"{'on' if view.with_intra_country else 'off'} · "
        f"Intra-region: {'on' if view.with_intra_region else 'off'}"
    )
    return " · ".join(parts) if parts else "No flow data in range"


def make_kpi_table_html(view: ViewResult) -> str:
    """Five KPI metrics matching export_pace make_kpi_strip."""
    if view.as_of is not None:
        dom = view.as_of.day
    elif len(view.current.index):
        dom = int(view.current.index[-1])
    else:
        dom = 1

    mtd = _value_at_day(view.current, dom)
    median = _value_at_day(view.band["median"], dom)
    last_yr = _value_at_day(view.last_yr, dom)
    projected_eom = mtd / dom * view.days_in_month if dom else float("nan")

    pct = view.percentile_rank
    pct_text = f"{pct:.0f}th" if pct is not None and pct == pct else "—"
    pct_sub = f"vs {view.n_history} prior {calendar.month_name[view.month]}s"

    rows = [
        (
            f"MTD {view.flow_direction_label} (day {dom})",
            f"{mtd:,.0f} {view.unit}" if mtd == mtd else "—",
            "",
        ),
        ("Historical percentile", pct_text, pct_sub),
        (
            f"vs {view.n_history}y median",
            _pct_delta(mtd, median),
            f"median: {median:,.0f} {view.unit}" if median == median else "",
        ),
        (
            "vs last year (same day)",
            _pct_delta(mtd, last_yr),
            f"last year: {last_yr:,.0f} {view.unit}" if last_yr == last_yr else "",
        ),
        (
            "Run-rate month-end (proj.)",
            f"{projected_eom:,.0f} {view.unit}" if projected_eom == projected_eom else "—",
            "MTD / days elapsed × days in month",
        ),
    ]

    body = "".join(
        f"<tr><td>{title}</td><td><strong>{value}</strong></td>"
        f"<td class='kpi-sub'>{sub}</td></tr>"
        for title, value, sub in rows
    )
    return f"""
<table class="kpi-table">
  <thead>
    <tr><th>Metric</th><th>Value</th><th>Detail</th></tr>
  </thead>
  <tbody>{body}</tbody>
</table>"""
