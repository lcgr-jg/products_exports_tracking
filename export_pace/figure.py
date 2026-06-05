from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime

import plotly.graph_objects as go
from dash import html
import dash_bootstrap_components as dbc

from export_pace.data import ViewResult


@dataclass(frozen=True)
class FigureOptions:
    show_bands: bool = True
    show_median: bool = True
    show_last_month: bool = True
    show_last_year: bool = True
    show_hist_years: bool = False
    compare_locations: bool = False
    compare_products: bool = False
    show_anomalies: bool = True


def _pct_delta(current: float, reference: float) -> str:
    if reference == 0 or reference != reference or current != current:
        return "—"
    pct = (current / reference - 1) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _value_at_day(series, day: int) -> float:
    if day not in series.index:
        prior = series[series.index <= day]
        return float(prior.iloc[-1]) if len(prior) else float("nan")
    return float(series.loc[day])


def make_figure(view: ViewResult, opts: FigureOptions | None = None) -> go.Figure:
    opts = opts or FigureOptions()
    month_name = calendar.month_name[view.month]
    unit_label = "kb" if view.unit == "kb" else "kbd (cumulated)"
    x = view.band.index

    fig = go.Figure()

    if opts.show_bands:
        fig.add_trace(
            go.Scatter(x=x, y=view.band["max"], line=dict(width=0), hoverinfo="skip", showlegend=False)
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["min"],
                fill="tonexty",
                line=dict(width=0),
                fillcolor="rgba(158,202,225,0.30)",
                name=f"{view.n_history}y range (min–max)",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(x=x, y=view.band["p75"], line=dict(width=0), hoverinfo="skip", showlegend=False)
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["p25"],
                fill="tonexty",
                line=dict(width=0),
                fillcolor="rgba(107,174,214,0.45)",
                name=f"{view.n_history}y IQR (25–75%)",
                hoverinfo="skip",
            )
        )

    if opts.show_median:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["median"],
                name=f"{view.n_history}y median",
                line=dict(color="#2171b5", width=2),
            )
        )

    if opts.show_last_month:
        fig.add_trace(
            go.Scatter(
                x=view.last_mo.index,
                y=view.last_mo.values,
                name="Last month",
                line=dict(color="#9e9ac8", width=2),
            )
        )

    if opts.show_last_year:
        fig.add_trace(
            go.Scatter(
                x=view.last_yr.index,
                y=view.last_yr.values,
                name="Last year",
                line=dict(color="#74c476", width=2),
            )
        )

    if opts.show_hist_years and not view.hist_by_year.empty:
        for year in sorted(view.hist_by_year.columns):
            fig.add_trace(
                go.Scatter(
                    x=view.hist_by_year.index,
                    y=view.hist_by_year[year],
                    name=str(year),
                    line=dict(color="rgba(150,150,150,0.45)", width=1),
                    legendgroup="hist_years",
                    showlegend=False,
                    hovertemplate=f"{year}<br>Day %{{x}}: %{{y:,.0f}}<extra></extra>",
                )
            )

    palette = ["#e6550d", "#756bb1", "#31a354", "#d95f0e", "#1f78b4", "#e7298a", "#66a61e"]
    show_products = opts.compare_products and len(view.product_series) > 1
    show_locations = opts.compare_locations and len(view.location_series) > 1
    if show_products:
        for i, (label, series) in enumerate(view.product_series.items()):
            fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    name=label,
                    line=dict(color=palette[i % len(palette)], width=2.5),
                )
            )
    elif show_locations:
        for i, (label, series) in enumerate(view.location_series.items()):
            fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    name=label,
                    line=dict(color=palette[i % len(palette)], width=2.5),
                )
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=view.current.index,
                y=view.current.values,
                name="Current month",
                line=dict(color="#e6550d", width=3, dash="dot"),
            )
        )

    as_of_note = ""
    if view.as_of is not None:
        as_of_note = f" — view as of {view.as_of.strftime('%d %b %Y')}"

    fig.update_layout(
        title=(
            f"Cumulative {view.product_label} exports — {view.location_label} — "
            f"{month_name} {view.target_year}{as_of_note}"
            + ("  (MOCK DATA)" if view.use_mock else "")
        ),
        xaxis_title="Day of month",
        yaxis_title=f"Cumulative {unit_label} (MTD)",
        xaxis=dict(range=[1, 31], dtick=2),
        template="plotly_white",
        legend=dict(orientation="h", y=-0.18),
        height=480,
        margin=dict(b=90),
    )
    return fig


def make_destination_figure(view: ViewResult, *, top_n: int = 10) -> go.Figure | None:
    if view.destinations_mtd.empty:
        return None
    month_name = calendar.month_name[view.month]
    top = view.destinations_mtd.head(top_n).sort_values()
    fig = go.Figure(
        go.Bar(
            x=top.values,
            y=top.index,
            orientation="h",
            marker_color="#6baed6",
            text=[f"{v:,.0f}" for v in top.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=f"Top destinations — {view.product_label} exports MTD — {month_name} {view.target_year}",
        xaxis_title=f"MTD {view.unit}",
        yaxis_title="",
        template="plotly_white",
        height=max(220, 40 + 28 * len(top)),
        margin=dict(l=10, r=40, t=50, b=40),
        showlegend=False,
    )
    return fig


def _installation_palette() -> list[str]:
    return [
        "#3182bd",
        "#6baed6",
        "#9ecae1",
        "#c6dbef",
        "#e6550d",
        "#fd8d3c",
        "#fdae6b",
        "#31a354",
    ]


def make_origin_cumulative_figure(view: ViewResult) -> go.Figure | None:
    """Stacked area of cumulative MTD exports by origin installation (Kpler-style)."""
    if view.origin_cumulative is None or view.origin_cumulative.empty:
        return None
    month_name = calendar.month_name[view.month]
    fig = go.Figure()
    palette = _installation_palette()
    for i, col in enumerate(view.origin_cumulative.columns):
        fig.add_trace(
            go.Scatter(
                x=view.origin_cumulative.index,
                y=view.origin_cumulative[col],
                name=col,
                stackgroup="installations",
                mode="lines",
                line=dict(width=0.5, color=palette[i % len(palette)]),
                fillcolor=palette[i % len(palette)],
            )
        )
    fig.update_layout(
        title=(
            f"Cumulative MTD by installation — {view.location_label} — "
            f"{month_name} {view.target_year}"
        ),
        xaxis_title="Day of month",
        yaxis_title=f"Cumulative {view.unit} (MTD)",
        xaxis=dict(range=[1, 31], dtick=2),
        template="plotly_white",
        height=300,
        legend=dict(orientation="h", y=-0.22),
        margin=dict(b=80),
    )
    return fig


def make_heatmap_figure(view: ViewResult) -> go.Figure | None:
    if view.heatmap_pct.empty:
        return None
    month_name = calendar.month_name[view.month]
    z = view.heatmap_pct.values
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=view.heatmap_pct.columns,
            y=[str(y) for y in view.heatmap_pct.index],
            colorscale="Blues",
            zmin=0,
            zmax=100,
            colorbar=dict(title="% of month"),
            hovertemplate="Year %{y}<br>Day %{x}<br>%{z:.0f}% of month total<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Month pacing heatmap — {month_name} — {view.location_label}",
        xaxis_title="Day of month",
        yaxis_title="Year",
        template="plotly_white",
        height=max(220, 36 + 28 * len(view.heatmap_pct.index)),
        margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig


def make_daily_figure(view: ViewResult, opts: FigureOptions | None = None) -> go.Figure:
    opts = opts or FigureOptions()
    month_name = calendar.month_name[view.month]
    unit_label = "kb" if view.unit == "kb" else "kbd"
    anomaly_set = set(view.anomaly_days) if opts.show_anomalies else set()
    colors = [
        "#e6550d" if day in anomaly_set else "#6baed6"
        for day in view.current_daily.index
    ]

    fig = go.Figure(
        go.Bar(
            x=view.current_daily.index,
            y=view.current_daily.values,
            name="Daily exports",
            marker_color=colors,
        )
    )
    anomaly_note = ""
    if anomaly_set:
        anomaly_note = f" — {len(anomaly_set)} high-volume day(s) flagged (>2σ vs history)"

    fig.update_layout(
        title=f"Daily {view.product_label} exports — {month_name} {view.target_year}{anomaly_note}",
        xaxis_title="Day of month",
        yaxis_title=f"{unit_label} / day",
        xaxis=dict(range=[0.5, 31.5], dtick=2),
        template="plotly_white",
        height=280,
        margin=dict(t=50, b=50),
        showlegend=False,
    )
    return fig


def make_data_status_line(view: ViewResult, *, refreshed_at: datetime | None = None) -> html.Div:
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
    if not parts:
        parts.append("No flow data in range")
    return html.Div(
        html.Small(" · ".join(parts), className="text-muted"),
        className="mb-2",
    )


def make_kpi_strip(view: ViewResult) -> list:
    if view.as_of is not None:
        dom = view.as_of.day
    elif len(view.current.index):
        dom = int(view.current.index[-1])
    else:
        dom = 1

    mtd = _value_at_day(view.current, dom)
    median = _value_at_day(view.band["median"], dom)
    last_yr = _value_at_day(view.last_yr, dom)
    days_elapsed = dom
    projected_eom = mtd / days_elapsed * view.days_in_month if days_elapsed else float("nan")

    def kpi_card(title: str, value: str, subtitle: str = "") -> dbc.Col:
        return dbc.Col(
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(title, className="text-muted small"),
                        html.Div(value, className="fs-5 fw-semibold"),
                        html.Div(subtitle, className="text-muted small"),
                    ]
                ),
                className="h-100",
            ),
            lg=2,
            md=4,
            sm=6,
            xs=12,
        )

    pct = view.percentile_rank
    pct_text = f"{pct:.0f}th" if pct is not None and pct == pct else "—"
    pct_sub = f"vs {view.n_history} prior {calendar.month_name[view.month]}s" if pct is not None else ""

    return dbc.Row(
        [
            kpi_card(
                f"MTD exports (day {dom})",
                f"{mtd:,.0f} {view.unit}" if mtd == mtd else "—",
            ),
            kpi_card("Historical percentile", pct_text, pct_sub),
            kpi_card(
                f"vs {view.n_history}y median",
                _pct_delta(mtd, median),
                f"median: {median:,.0f} {view.unit}" if median == median else "",
            ),
            kpi_card(
                "vs last year (same day)",
                _pct_delta(mtd, last_yr),
                f"last year: {last_yr:,.0f} {view.unit}" if last_yr == last_yr else "",
            ),
            kpi_card(
                "Run-rate month-end (proj.)",
                f"{projected_eom:,.0f} {view.unit}" if projected_eom == projected_eom else "—",
                "MTD / days elapsed × days in month",
            ),
        ],
        className="g-3 mb-3",
    )
